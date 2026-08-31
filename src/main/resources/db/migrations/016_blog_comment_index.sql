-- Supports note-detail comment lists and aggregate comment-count refreshes.
-- Safe to rerun against an existing database.

SET @NYC_REVIEW_BLOG_COMMENT_INDEX_SQL = IF(
    EXISTS(
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'tb_blog_comments'
          AND INDEX_NAME = 'idx_blog_comments_blog_time'
    ),
    'DO 0',
    'ALTER TABLE `tb_blog_comments` ADD INDEX `idx_blog_comments_blog_time` (`blog_id`, `create_time`)'
);

PREPARE NYC_REVIEW_BLOG_COMMENT_INDEX FROM @NYC_REVIEW_BLOG_COMMENT_INDEX_SQL;
EXECUTE NYC_REVIEW_BLOG_COMMENT_INDEX;
DEALLOCATE PREPARE NYC_REVIEW_BLOG_COMMENT_INDEX;
