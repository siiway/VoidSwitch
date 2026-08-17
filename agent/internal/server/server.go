// Package server wires the HTTP server with optional TLS + HTTP/2 and runs it.
package server

import (
	"context"
	"crypto/tls"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"time"

	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"

	"github.com/siiway/voidswitch-agent/internal/config"
)

// Run starts the agent server and blocks until ctx is cancelled or the server
// fails. It returns the server error (nil on graceful shutdown).
func Run(ctx context.Context, cfg *config.Config, handler http.Handler, log *slog.Logger) error {
	readTimeout := time.Duration(cfg.IdleTimeout) * time.Second
	h2s := &http2.Server{MaxConcurrentStreams: uint32(cfg.MaxStreams)}
	server := &http.Server{
		Addr:              cfg.Listen,
		Handler:           h2c.NewHandler(handler, h2s),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       readTimeout,
		WriteTimeout:      0, // streaming — no overall write cap
		IdleTimeout:       readTimeout,
		TLSConfig:         &tls.Config{MinVersion: tls.VersionTLS12},
	}
	if cfg.Mode == "connect" {
		// CONNECT works over both HTTP/1.1 and HTTP/2; h2c handler covers h2c.
		server.Handler = handler
	}
	if cfg.TLSCert != "" && cfg.TLSKey != "" {
		err := http2.ConfigureServer(server, h2s)
		if err != nil {
			return err
		}
	}

	ln, err := net.Listen("tcp", cfg.Listen)
	if err != nil {
		return err
	}
	log.Info("serving", "listen", cfg.Listen, "mode", cfg.Mode, "tls", cfg.TLSCert != "")

	errc := make(chan error, 1)
	go func() {
		if cfg.TLSCert != "" && cfg.TLSKey != "" {
			errc <- server.ServeTLS(ln, cfg.TLSCert, cfg.TLSKey)
		} else {
			errc <- server.Serve(ln)
		}
	}()

	select {
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
		return nil
	case err := <-errc:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	}
}
