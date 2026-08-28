package com.nycreview.agentapi.service;

import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.nycreview.agentapi.dto.AgentBusinessHours;
import com.nycreview.agentapi.dto.AgentEvidenceCitation;
import com.nycreview.agentapi.dto.AgentShopCandidate;
import com.nycreview.agentapi.dto.AgentShopEvidence;
import com.nycreview.agentapi.dto.AgentShopSearchRequest;
import com.nycreview.entity.Blog;
import com.nycreview.entity.Shop;
import com.nycreview.entity.ShopBusinessHours;
import com.nycreview.entity.ShopReview;
import com.nycreview.entity.ShopSubcategory;
import com.nycreview.entity.ShopTag;
import com.nycreview.entity.ShopType;
import com.nycreview.mapper.ShopBusinessHoursMapper;
import com.nycreview.mapper.ShopSubcategoryMapper;
import com.nycreview.mapper.ShopTagMapper;
import com.nycreview.service.IBlogService;
import com.nycreview.service.IShopReviewService;
import com.nycreview.service.IShopService;
import com.nycreview.service.IShopTypeService;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class AgentShopToolService {

    static final int DEFAULT_LIMIT = 5;
    // P12 retrieves a broad structured pool and lets the Agent's hybrid RAG
    // reranker select the final five merchants. The endpoint remains internal
    // and all public/MCP result limits keep their existing contracts.
    static final int MAX_LIMIT = 100;
    static final int MAX_EVIDENCE_LIMIT = 50;

    private final IShopService shopService;
    private final IShopTypeService shopTypeService;
    private final IShopReviewService shopReviewService;
    private final IBlogService blogService;
    private final ShopTagMapper shopTagMapper;
    private final ShopBusinessHoursMapper shopBusinessHoursMapper;
    private final ShopSubcategoryMapper shopSubcategoryMapper;

    public AgentShopToolService(
            IShopService shopService,
            IShopTypeService shopTypeService,
            IShopReviewService shopReviewService,
            IBlogService blogService,
            ShopTagMapper shopTagMapper,
            ShopBusinessHoursMapper shopBusinessHoursMapper,
            ShopSubcategoryMapper shopSubcategoryMapper
    ) {
        this.shopService = shopService;
        this.shopTypeService = shopTypeService;
        this.shopReviewService = shopReviewService;
        this.blogService = blogService;
        this.shopTagMapper = shopTagMapper;
        this.shopBusinessHoursMapper = shopBusinessHoursMapper;
        this.shopSubcategoryMapper = shopSubcategoryMapper;
    }

    public SearchResult search(AgentShopSearchRequest request) {
        AgentShopSearchRequest safeRequest = request == null
                ? new AgentShopSearchRequest(null, null, null, null, null, null, null, List.of(), null)
                : request;
        int limit = normalizeLimit(safeRequest.limit());
        int fetchLimit = Math.max(100, limit * 10);
        Long maxAvgPrice = safeRequest.maxAvgPriceCents() == null
                ? null
                : Math.max(0L, safeRequest.maxAvgPriceCents() / 100L);

        var query = shopService.query()
                .like(StrUtil.isNotBlank(safeRequest.query()), "name", safeRequest.query())
                .eq(safeRequest.typeId() != null, "type_id", safeRequest.typeId())
                // P8 stores the official NTA display name (for example,
                // "Midtown-Times Square"). Natural-language constraints and
                // saved preferences may still use the shorter "Midtown" form.
                .like(StrUtil.isNotBlank(safeRequest.neighborhood()), "area", safeRequest.neighborhood())
                .eq("business_status", "OPERATIONAL")
                // A missing public price is unknown, not over budget. Keep it
                // available for the verifier to disclose instead of silently
                // excluding a real shop.
                .and(maxAvgPrice != null,
                        wrapper -> wrapper.le("avg_price", maxAvgPrice).or().isNull("avg_price"))
                .orderByDesc("score")
                .orderByDesc("comments")
                .last("LIMIT " + fetchLimit);

        List<Shop> shops = query.list();
        Map<Long, ShopType> typeMap = shopTypeService.list().stream()
                .collect(Collectors.toMap(ShopType::getId, Function.identity(), (first, ignored) -> first));
        Enrichment enrichment = loadEnrichment(shops);
        Set<String> requiredTags = safeRequest.requiredTags() == null
                ? Set.of()
                : Set.copyOf(safeRequest.requiredTags());
        List<String> warnings = new ArrayList<>();

        List<AgentShopCandidate> candidates = shops.stream()
                .map(shop -> toCandidate(
                        shop,
                        typeMap,
                        enrichment,
                        safeRequest.latitude(),
                        safeRequest.longitude()
                ))
                .filter(candidate -> candidate.tags().containsAll(requiredTags))
                .filter(candidate -> withinRadius(candidate, safeRequest.radiusMeters()))
                .sorted(candidateComparator(safeRequest.latitude(), safeRequest.longitude()))
                .limit(limit)
                .toList();
        if (candidates.isEmpty()) {
            warnings.add("No NYC shops matched every hard constraint.");
        }
        return new SearchResult(candidates, warnings);
    }

    public AgentShopCandidate detail(Long shopId) {
        if (shopId == null || shopId <= 0) {
            return null;
        }
        Shop shop = shopService.getById(shopId);
        if (shop == null) {
            return null;
        }
        Map<Long, ShopType> typeMap = shopTypeService.list().stream()
                .collect(Collectors.toMap(ShopType::getId, Function.identity(), (first, ignored) -> first));
        return toCandidate(shop, typeMap, loadEnrichment(List.of(shop)), null, null);
    }

    private Enrichment loadEnrichment(List<Shop> shops) {
        if (shops.isEmpty()) {
            return Enrichment.empty();
        }
        List<Long> shopIds = shops.stream().map(Shop::getId).toList();
        Map<Long, List<String>> tagsByShop = shopTagMapper.selectList(
                        Wrappers.lambdaQuery(ShopTag.class)
                                .in(ShopTag::getShopId, shopIds)
                                .orderByAsc(ShopTag::getTag)
                ).stream()
                .collect(Collectors.groupingBy(
                        ShopTag::getShopId,
                        Collectors.mapping(ShopTag::getTag, Collectors.toList())
                ));
        Map<Long, List<AgentBusinessHours>> hoursByShop = shopBusinessHoursMapper.selectList(
                        Wrappers.lambdaQuery(ShopBusinessHours.class)
                                .in(ShopBusinessHours::getShopId, shopIds)
                                .orderByAsc(ShopBusinessHours::getDayOfWeek)
                ).stream()
                .collect(Collectors.groupingBy(
                        ShopBusinessHours::getShopId,
                        Collectors.mapping(AgentShopToolService::toBusinessHours, Collectors.toList())
                ));
        List<Long> subcategoryIds = shops.stream()
                .map(Shop::getSubcategoryId)
                .filter(java.util.Objects::nonNull)
                .distinct()
                .toList();
        Map<Long, ShopSubcategory> subcategoryById = subcategoryIds.isEmpty()
                ? Map.of()
                : shopSubcategoryMapper.selectBatchIds(subcategoryIds).stream()
                .collect(Collectors.toMap(
                        ShopSubcategory::getId,
                        Function.identity(),
                        (first, ignored) -> first
                ));
        return new Enrichment(tagsByShop, hoursByShop, subcategoryById);
    }

    private static AgentBusinessHours toBusinessHours(ShopBusinessHours hours) {
        return new AgentBusinessHours(
                hours.getDayOfWeek(),
                Boolean.TRUE.equals(hours.getClosed()),
                hours.getOpenTime(),
                hours.getCloseTime(),
                Boolean.TRUE.equals(hours.getClosesNextDay())
        );
    }

    public AgentShopEvidence evidence(Long shopId, Integer requestedLimit) {
        int limit = normalizeEvidenceLimit(requestedLimit);
        List<AgentEvidenceCitation> citations = new ArrayList<>();
        List<ShopReview> threads = shopReviewService.queryThreadsForEvidence(shopId, limit);
        for (ShopReview review : threads) {
            String sourceType = threadSourceType(review);
            citations.add(new AgentEvidenceCitation(
                    "shop-review-thread-" + review.getId(),
                    shopId,
                    "shop_review_thread",
                    "shop_review_thread:" + review.getId(),
                    excerpt(reviewThreadText(review)),
                    review.getCreateTime(),
                    true,
                    sourceType,
                    threadIsSynthetic(review),
                    review.getRootId() == null ? review.getId() : review.getRootId(),
                    maxThreadDepth(review),
                    threadReplyCount(review)
            ));
        }

        int remaining = Math.max(0, limit - citations.size());
        if (remaining > 0) {
            List<Blog> blogs = blogService.query()
                    .eq("shop_id", shopId)
                    .orderByDesc("create_time")
                    .last("LIMIT " + remaining)
                    .list();
            for (Blog blog : blogs) {
                String sourceType = StrUtil.blankToDefault(blog.getSourceType(), "LEGACY");
                String content = StrUtil.isBlank(blog.getTitle())
                        ? blog.getContent()
                        : blog.getTitle() + "\n" + blog.getContent();
                citations.add(new AgentEvidenceCitation(
                        "blog-" + blog.getId(),
                        shopId,
                        "blog",
                        "blog:" + blog.getId(),
                        excerpt(content),
                        blog.getCreateTime(),
                        true,
                        sourceType,
                        "SYNTHETIC".equalsIgnoreCase(sourceType),
                        null,
                        0,
                        0
                ));
            }
        }
        return new AgentShopEvidence(shopId, List.copyOf(citations));
    }

    private AgentShopCandidate toCandidate(
            Shop shop,
            Map<Long, ShopType> typeMap,
            Enrichment enrichment,
            Double latitude,
            Double longitude
    ) {
        Integer distance = latitude == null || longitude == null
                ? null
                : haversineMeters(latitude, longitude, shop.getY(), shop.getX());
        ShopType type = typeMap.get(shop.getTypeId());
        ShopSubcategory subcategory = enrichment.subcategoryById().get(shop.getSubcategoryId());
        return new AgentShopCandidate(
                shop.getId(),
                shop.getName(),
                shop.getTypeId(),
                type == null ? null : type.getName(),
                shop.getSubcategoryId(),
                subcategory == null ? null : subcategory.getName(),
                shop.getBorough(),
                shop.getArea(),
                shop.getAddress(),
                shop.getDescription(),
                shop.getY(),
                shop.getX(),
                shop.getAvgPrice() == null ? null : shop.getAvgPrice() * 100L,
                shop.getPriceLevel(),
                shop.getScore() == null ? null : shop.getScore() / 10.0,
                shop.getComments(),
                shop.getLocalReviewCount() == null ? shop.getComments() : shop.getLocalReviewCount(),
                shop.getLocalScore() == null ? null : shop.getLocalScore() / 10.0,
                shop.getRatingCount(),
                shop.getExternalRatingCount() == null ? shop.getRatingCount() : shop.getExternalRatingCount(),
                shop.getExternalScore() == null ? null : shop.getExternalScore() / 10.0,
                shop.getPriceRangeText(),
                shop.getPhone(),
                shop.getWebsite(),
                shop.getReservationUrl(),
                shop.getBusinessStatus(),
                shop.getHealthGrade(),
                distance,
                shop.getTimezone(),
                shop.getSourceType(),
                shop.getExternalId(),
                shop.getSourceName(),
                shop.getSourceUrl(),
                shop.getSourceFetchedAt(),
                shop.getSyntheticFields() == null ? List.of() : shop.getSyntheticFields(),
                shop.getDataVersion(),
                enrichment.tagsByShop().getOrDefault(shop.getId(), List.of()),
                enrichment.hoursByShop().getOrDefault(shop.getId(), List.of())
        );
    }

    private static boolean withinRadius(AgentShopCandidate candidate, Integer radiusMeters) {
        return radiusMeters == null
                || radiusMeters <= 0
                || candidate.distanceMeters() == null
                || candidate.distanceMeters() <= radiusMeters;
    }

    private static Comparator<AgentShopCandidate> candidateComparator(Double latitude, Double longitude) {
        if (latitude != null && longitude != null) {
            return Comparator
                    .comparing(AgentShopCandidate::distanceMeters, Comparator.nullsLast(Integer::compareTo))
                    .thenComparing(AgentShopCandidate::score, Comparator.nullsLast(Comparator.reverseOrder()));
        }
        return Comparator.comparing(
                AgentShopCandidate::score,
                Comparator.nullsLast(Comparator.reverseOrder())
        );
    }

    static int normalizeLimit(Integer requested) {
        if (requested == null) {
            return DEFAULT_LIMIT;
        }
        return Math.max(1, Math.min(requested, MAX_LIMIT));
    }

    static int normalizeEvidenceLimit(Integer requested) {
        if (requested == null) {
            return 20;
        }
        return Math.max(1, Math.min(requested, MAX_EVIDENCE_LIMIT));
    }

    static String excerpt(String content) {
        if (content == null) {
            return "";
        }
        String normalized = cleanDisplayContent(content);
        return normalized.length() <= 500 ? normalized : normalized.substring(0, 500);
    }

    static String cleanDisplayContent(String content) {
        if (content == null) {
            return "";
        }
        return content
                .replaceAll("(?i)\\[(?:synthetic\\s+(?:demo\\s+)?(?:review|reply|follow-up|post)|synthetic\\s+security-test\\s+review)]\\s*", "")
                .replaceAll("(?im)^\\s*\\[(?:level\\s+\\d+[^]]*|root|reply\\s+depth=\\d+)]\\s*", "")
                .replaceAll("(?i)\\bThis generated scenario describes\\s+", "")
                .replaceAll("(?i)\\s*(?:Merchant identity is source-backed; this post, media and promotions are synthetic\\.|It is not a real user visit; prices and hours are synthetic\\.)", "")
                .strip();
    }

    static String reviewThreadText(ShopReview root) {
        StringBuilder content = new StringBuilder();
        appendReviewThread(content, root, 0);
        return content.toString().strip();
    }

    private static void appendReviewThread(StringBuilder content, ShopReview review, int fallbackDepth) {
        int depth = review.getDepth() == null ? fallbackDepth : review.getDepth();
        if (!content.isEmpty()) {
            content.append('\n');
        }
        content.append(cleanDisplayContent(review.getContent()));
        if (review.getChildren() == null) {
            return;
        }
        for (ShopReview child : review.getChildren()) {
            appendReviewThread(content, child, depth + 1);
        }
    }

    static int maxThreadDepth(ShopReview root) {
        int current = root.getDepth() == null ? 0 : root.getDepth();
        if (root.getChildren() == null || root.getChildren().isEmpty()) {
            return current;
        }
        return Math.max(current, root.getChildren().stream()
                .mapToInt(AgentShopToolService::maxThreadDepth)
                .max()
                .orElse(current));
    }

    static int threadReplyCount(ShopReview root) {
        if (root.getChildren() == null || root.getChildren().isEmpty()) {
            return 0;
        }
        return root.getChildren().stream()
                .mapToInt(child -> 1 + threadReplyCount(child))
                .sum();
    }

    static String threadSourceType(ShopReview root) {
        java.util.Set<String> sources = new java.util.LinkedHashSet<>();
        collectThreadSources(root, sources);
        return sources.size() == 1 ? sources.iterator().next() : "MIXED";
    }

    static boolean threadIsSynthetic(ShopReview root) {
        return "SYNTHETIC".equalsIgnoreCase(threadSourceType(root));
    }

    private static void collectThreadSources(ShopReview review, java.util.Set<String> sources) {
        sources.add(StrUtil.blankToDefault(review.getSourceType(), "LEGACY").toUpperCase());
        if (review.getChildren() == null) {
            return;
        }
        for (ShopReview child : review.getChildren()) {
            collectThreadSources(child, sources);
        }
    }

    static int haversineMeters(double latitude1, double longitude1, double latitude2, double longitude2) {
        double earthRadius = 6_371_000;
        double latitudeDelta = Math.toRadians(latitude2 - latitude1);
        double longitudeDelta = Math.toRadians(longitude2 - longitude1);
        double firstLatitude = Math.toRadians(latitude1);
        double secondLatitude = Math.toRadians(latitude2);
        double value = Math.sin(latitudeDelta / 2) * Math.sin(latitudeDelta / 2)
                + Math.cos(firstLatitude) * Math.cos(secondLatitude)
                * Math.sin(longitudeDelta / 2) * Math.sin(longitudeDelta / 2);
        return (int) Math.round(earthRadius * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value)));
    }

    public record SearchResult(List<AgentShopCandidate> candidates, List<String> warnings) {
    }

    private record Enrichment(
            Map<Long, List<String>> tagsByShop,
            Map<Long, List<AgentBusinessHours>> hoursByShop,
            Map<Long, ShopSubcategory> subcategoryById
    ) {
        static Enrichment empty() {
            return new Enrichment(Map.of(), Map.of(), Map.of());
        }
    }
}
