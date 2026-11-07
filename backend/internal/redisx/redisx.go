// Package redisx wraps go-redis with the namespaced coordination primitives the
// Python backend provided: cross-worker sliding-window rate limiting, task/SSE
// leases, and settings pub/sub propagation.
package redisx

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"time"

	"github.com/redis/go-redis/v9"
)

// Config describes the Redis connection.
type Config struct {
	URL         string
	KeyPrefix   string
	MaxConns    int
	DialTimeout time.Duration
	IOTimeout   time.Duration
}

// Service is the process-wide Redis client.
type Service struct {
	client *redis.Client
	prefix string
}

func New(ctx context.Context, cfg Config) (*Service, error) {
	opt, err := redis.ParseURL(cfg.URL)
	if err != nil {
		return nil, err
	}
	if cfg.MaxConns > 0 {
		opt.PoolSize = cfg.MaxConns
	}
	if cfg.DialTimeout > 0 {
		opt.DialTimeout = cfg.DialTimeout
	}
	if cfg.IOTimeout > 0 {
		opt.ReadTimeout = cfg.IOTimeout
		opt.WriteTimeout = cfg.IOTimeout
	}
	c := redis.NewClient(opt)
	if err := c.Ping(ctx).Err(); err != nil {
		_ = c.Close()
		return nil, err
	}
	prefix := cfg.KeyPrefix
	if prefix == "" {
		prefix = "voidswitch"
	}
	return &Service{client: c, prefix: prefix}, nil
}

func (s *Service) Client() *redis.Client { return s.client }

// Key builds a namespaced key: "<prefix>:<part>:<part>…".
func (s *Service) Key(parts ...string) string {
	out := s.prefix
	for _, p := range parts {
		out += ":" + p
	}
	return out
}

func (s *Service) Ping(ctx context.Context) error { return s.client.Ping(ctx).Err() }
func (s *Service) Close() error                   { return s.client.Close() }

// ---- leases ---------------------------------------------------------------

const leaseReleaseScript = `if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end`
const leaseRenewScript = `if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end`

// AcquireLease tries to take a lease. Returns (released-fn, acquired).
// When acquired, a background goroutine renews it until released or the ctx is
// cancelled.
func (s *Service) AcquireLease(ctx context.Context, name string, ttl time.Duration) (func(), bool) {
	key := s.Key("lease", name)
	owner := randomHex(16)
	ttlMS := ttl.Milliseconds()
	if ttlMS < 1 {
		ttlMS = 1
	}
	ok, err := s.client.SetNX(ctx, key, owner, time.Duration(ttlMS)*time.Millisecond).Result()
	if err != nil || !ok {
		return func() {}, false
	}

	stop := make(chan struct{})
	go func() {
		interval := ttl / 3
		if interval < 10*time.Millisecond {
			interval = 10 * time.Millisecond
		}
		t := time.NewTicker(interval)
		defer t.Stop()
		for {
			select {
			case <-stop:
				return
			case <-t.C:
				n, err := s.client.Eval(context.Background(), leaseRenewScript, []string{key}, owner, ttlMS).Int()
				if err != nil || n == 0 {
					return
				}
			}
		}
	}()

	released := false
	return func() {
		if released {
			return
		}
		released = true
		close(stop)
		_ = s.client.Eval(context.Background(), leaseReleaseScript, []string{key}, owner).Err()
	}, true
}

func randomHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}
