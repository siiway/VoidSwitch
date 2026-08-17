// Command voidswitch-agent is a minimal, single-binary outbound relay for
// VoidSwitch. It accepts token-authenticated outbound traffic from the gateway
// and forwards it to the real upstream, providing a clean egress IP, upstream
// connection pooling, and (via --mode connect) a plain CONNECT proxy fallback.
package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/siiway/voidswitch-agent/internal/config"
	"github.com/siiway/voidswitch-agent/internal/relay"
	"github.com/siiway/voidswitch-agent/internal/server"
)

func main() {
	cfg, err := config.Parse(os.Args[1:])
	if err != nil {
		// flag package already printed usage for parse errors.
		if err == config.ErrHelp {
			os.Exit(0)
		}
		slog.Error("config", "err", err)
		os.Exit(2)
	}
	level := slog.LevelInfo
	switch cfg.LogLevel {
	case "debug":
		level = slog.LevelDebug
	case "warn":
		level = slog.LevelWarn
	case "error":
		level = slog.LevelError
	}
	log := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: level}))

	agent, err := relay.New(cfg, log)
	if err != nil {
		log.Error("init", "err", err)
		os.Exit(2)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := server.Run(ctx, cfg, agent.Handler(), log); err != nil {
		log.Error("server", "err", err)
		os.Exit(1)
	}
}
