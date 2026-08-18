package com.hmdp.agentapi.service;

import cn.hutool.core.util.StrUtil;
import com.hmdp.agentapi.dto.AgentEvidenceCitation;
import com.hmdp.agentapi.dto.AgentShopCandidate;
import com.hmdp.agentapi.dto.AgentShopEvidence;
import com.hmdp.agentapi.dto.AgentShopSearchRequest;
import com.hmdp.entity.Blog;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopReview;
import com.hmdp.entity.ShopType;
import com.hmdp.service.IBlogService;
import com.hmdp.service.IShopReviewService;
import com.hmdp.service.IShopService;
import com.hmdp.service.IShopTypeService;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class AgentShopToolService {

    static final int DEFAULT_LIMIT = 5;
    static final int MAX_LIMIT = 20;
    static final int MAX_EVIDENCE_LIMIT = 50;

    private final IShopService shopService;
    private final IShopTypeService shopTypeService;
    private final IShopReviewService shopReviewService;
    private final IBlogService blogService;

    public AgentShopToolService(
            IShopService shopService,
            IShopTypeService shopTypeService,
            IShopReviewService shopReviewService,
            IBlogService blogService
    ) {
        this.shopService = shopService;
        this.shopTypeService = shopTypeService;
        this.shopReviewService = shopReviewService;
        this.blogService = blogService;
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
                .eq(StrUtil.isNotBlank(safeRequest.neighborhood()), "area", safeRequest.neighborhood())
                .le(maxAvgPrice != null, "avg_price", maxAvgPrice)
                .orderByDesc("score")
                .orderByDesc("comments")
                .last("LIMIT " + fetchLimit);

        List<Shop> shops = query.list();
        Map<Long, ShopType> typeMap = shopTypeService.list().stream()
                .collect(Collectors.toMap(ShopType::getId, Function.identity(), (first, ignored) -> first));
        List<String> warnings = new ArrayList<>();
        if (safeRequest.requiredTags() != null && !safeRequest.requiredTags().isEmpty()) {
            warnings.add("Tag filtering will be enabled after the NYC tag migration is applied.");
        }

        List<AgentShopCandidate> candidates = shops.stream()
                .map(shop -> toCandidate(shop, typeMap, safeRequest.latitude(), safeRequest.longitude()))
                .filter(candidate -> withinRadius(candidate, safeRequest.radiusMeters()))
                .sorted(candidateComparator(safeRequest.latitude(), safeRequest.longitude()))
                .limit(limit)
                .toList();
        return new SearchResult(candidates, warnings);
    }

    public AgentShopEvidence evidence(Long shopId, Integer requestedLimit) {
        int limit = normalizeEvidenceLimit(requestedLimit);
        List<AgentEvidenceCitation> citations = new ArrayList<>();
        List<ShopReview> reviews = shopReviewService.query()
                .eq("shop_id", shopId)
                .orderByDesc("create_time")
                .last("LIMIT " + limit)
                .list();
        for (ShopReview review : reviews) {
            citations.add(new AgentEvidenceCitation(
                    "shop-review-" + review.getId(),
                    shopId,
                    "shop_review",
                    "shop_review:" + review.getId(),
                    excerpt(review.getContent()),
                    review.getCreateTime(),
                    true
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
                        true
                ));
            }
        }
        return new AgentShopEvidence(shopId, List.copyOf(citations));
    }

    private AgentShopCandidate toCandidate(
            Shop shop,
            Map<Long, ShopType> typeMap,
            Double latitude,
            Double longitude
    ) {
        Integer distance = latitude == null || longitude == null
                ? null
                : haversineMeters(latitude, longitude, shop.getY(), shop.getX());
        ShopType type = typeMap.get(shop.getTypeId());
        return new AgentShopCandidate(
                shop.getId(),
                shop.getName(),
                shop.getTypeId(),
                type == null ? null : type.getName(),
                shop.getArea(),
                shop.getAddress(),
                shop.getY(),
                shop.getX(),
                shop.getAvgPrice() == null ? null : shop.getAvgPrice() * 100L,
                shop.getScore() == null ? null : shop.getScore() / 10.0,
                shop.getComments(),
                distance,
                List.of()
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
        String normalized = content.strip();
        return normalized.length() <= 500 ? normalized : normalized.substring(0, 500);
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
}
