package redisx

import (
	"context"
)

// Sliding-window rate limiting, ported from the Python backend's Lua scripts so
// the behaviour is identical across the cutover.

const acquireScript = `
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local cutoff = now_ms - tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], now_ms, ARGV[3])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[1]) + 1000)
return 1
`

const reserveAnyScript = `
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local best = 0
local best_remaining = 0
for i = 1, #KEYS do
  local window = tonumber(ARGV[(i - 1) * 2 + 1])
  local maximum = tonumber(ARGV[(i - 1) * 2 + 2])
  if maximum <= 0 or window <= 0 then return 1 end
  redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now_ms - window)
  local remaining = maximum - redis.call('ZCARD', KEYS[i])
  if remaining > best_remaining then best = i; best_remaining = remaining end
end
if best == 0 then return 0 end
local window = tonumber(ARGV[(best - 1) * 2 + 1])
redis.call('ZADD', KEYS[best], now_ms, ARGV[#ARGV])
redis.call('PEXPIRE', KEYS[best], window + 1000)
return 1
`

// RateLimiter is a namespaced Redis sliding-window limiter.
type RateLimiter struct {
	svc       *Service
	namespace string
}

func (s *Service) RateLimiter(namespace string) *RateLimiter {
	return &RateLimiter{svc: s, namespace: namespace}
}

// Acquire reserves one slot. Unlimited when max<=0 or window<=0.
func (r *RateLimiter) Acquire(ctx context.Context, key string, windowSeconds float64, max int) (bool, error) {
	if max <= 0 || windowSeconds <= 0 {
		return true, nil
	}
	windowMS := int64(windowSeconds * 1000)
	if windowMS < 1 {
		windowMS = 1
	}
	n, err := r.svc.client.Eval(ctx, acquireScript,
		[]string{r.svc.Key(r.namespace, key)},
		windowMS, max, randomHex(16)).Int()
	if err != nil {
		return false, err
	}
	return n == 1, nil
}

// LimitCandidate is one candidate limit for ReserveAny.
type LimitCandidate struct {
	Key           string
	WindowSeconds float64
	MaxRequests   int
}

// ReserveAny reserves a slot against the candidate with the most headroom.
func (r *RateLimiter) ReserveAny(ctx context.Context, candidates []LimitCandidate) (bool, error) {
	if len(candidates) == 0 {
		return true, nil
	}
	keys := make([]string, len(candidates))
	args := make([]any, 0, len(candidates)*2+1)
	for i, c := range candidates {
		keys[i] = r.svc.Key(r.namespace, c.Key)
		w := int64(c.WindowSeconds * 1000)
		if w < 1 {
			w = 1
		}
		args = append(args, w, c.MaxRequests)
	}
	args = append(args, randomHex(16))
	n, err := r.svc.client.Eval(ctx, reserveAnyScript, keys, args...).Int()
	if err != nil {
		return false, err
	}
	return n == 1, nil
}

