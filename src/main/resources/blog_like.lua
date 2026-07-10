local likedKey = KEYS[1]
local userId = ARGV[1]
local timestamp = ARGV[2]

if redis.call('zscore', likedKey, userId) then
    redis.call('zrem', likedKey, userId)
    return -1
end

redis.call('zadd', likedKey, timestamp, userId)
return 1
