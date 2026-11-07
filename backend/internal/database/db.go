package database

import (
	"context"
	"database/sql"
	"embed"
	"fmt"
	"log/slog"
	"net/url"
	"strings"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"
)

//go:embed migrations/*.sql
var migrationFS embed.FS

// BaselineAlembicHead is the Alembic revision the Python backend was at when
// the Go schema baseline was generated. A production database at this revision
// (or any ancestor the baseline heals idempotently) is compatible.
const (
	BaselineAlembicHead = "c4e8a1f7b2d9"
	baselineVersion     = 1
)

// DB wraps the GORM handle and the underlying *sql.DB.
type DB struct {
	Gorm *gorm.DB
	SQL  *sql.DB
}

// Open connects to PostgreSQL. The URL accepts both libpq DSNs and
// "postgres://" / "postgresql://" URLs. Python-style driver prefixes
// ("postgresql+asyncpg://") are normalised.
func Open(rawURL string, echo bool) (*DB, error) {
	dsn, err := normaliseDSN(rawURL)
	if err != nil {
		return nil, err
	}

	logLevel := gormlogger.Silent
	if echo {
		logLevel = gormlogger.Info
	}

	gdb, err := gorm.Open(postgres.Open(dsn), &gorm.Config{
		Logger: gormlogger.Default.LogMode(logLevel),
		// Never auto-create schema; goose owns it.
		DisableAutomaticPing: false,
		NowFunc:              func() time.Time { return time.Now().UTC() },
	})
	if err != nil {
		return nil, fmt.Errorf("open postgres: %w", err)
	}

	sqlDB, err := gdb.DB()
	if err != nil {
		return nil, fmt.Errorf("unwrap sql.DB: %w", err)
	}
	sqlDB.SetMaxOpenConns(15)
	sqlDB.SetMaxIdleConns(15)
	sqlDB.SetConnMaxLifetime(30 * time.Minute)
	sqlDB.SetConnMaxIdleTime(5 * time.Minute)

	return &DB{Gorm: gdb, SQL: sqlDB}, nil
}

func (d *DB) Close() error { return d.SQL.Close() }

func (d *DB) Ping(ctx context.Context) error { return d.SQL.PingContext(ctx) }

// normaliseDSN converts Python SQLAlchemy async URLs to libpq DSNs.
func normaliseDSN(raw string) (string, error) {
	if strings.TrimSpace(raw) == "" {
		return "", fmt.Errorf("database url is empty")
	}
	s := raw
	// Strip SQLAlchemy driver suffixes: postgresql+asyncpg:// → postgresql://
	if i := strings.Index(s, "+asyncpg://"); i >= 0 {
		s = s[:i] + "://" + s[i+len("+asyncpg://"):]
	}
	if i := strings.Index(s, "+psycopg://"); i >= 0 {
		s = s[:i] + "://" + s[i+len("+psycopg://"):]
	}
	if strings.HasPrefix(s, "postgresql://") {
		s = "postgres://" + strings.TrimPrefix(s, "postgresql://")
	}
	if !strings.HasPrefix(s, "postgres://") && !strings.HasPrefix(s, "host=") {
		return "", fmt.Errorf("unsupported database url (expect postgres/DSN): %s", maskDSN(raw))
	}
	return s, nil
}

// MaskDSN redacts the password for logging.
func maskDSN(raw string) string {
	if u, err := url.Parse(raw); err == nil && u.User != nil {
		if _, has := u.User.Password(); has {
			u.User = url.UserPassword(u.User.Username(), "***")
		}
		return u.String()
	}
	return raw
}

// MigrateResult describes what Migrate did.
type MigrateResult struct {
	Adopted bool  // an existing DB was adopted without replaying the baseline
	Applied int   // number of goose migrations applied
	Version int64 // final goose version
}

// Migrate runs goose migrations, adopting a pre-existing (Python-created) schema
// instead of replaying the baseline. It NEVER drops tables or data.
func (d *DB) Migrate(ctx context.Context) (MigrateResult, error) {
	goose.SetBaseFS(migrationFS)
	goose.SetSequential(true)
	goose.SetDialect("postgres")
	// Route goose output through slog-compatible quiet mode.
	goose.SetLogger(gooseLogger{})

	existing, err := tableExists(ctx, d.SQL, "users")
	if err != nil {
		return MigrateResult{}, fmt.Errorf("probe existing schema: %w", err)
	}

	res := MigrateResult{}

	if existing {
		// A populated database exists. Validate it matches our expectations, then
		// ensure goose considers the baseline already applied (do not run it).
		if err := ValidateSchema(ctx, d.SQL); err != nil {
			return res, fmt.Errorf("existing schema does not match expectations: %w", err)
		}
		hasVersion, err := tableExists(ctx, d.SQL, "goose_db_version")
		if err != nil {
			return res, err
		}
		if !hasVersion {
			if _, err := goose.EnsureDBVersionContext(ctx, d.SQL); err != nil {
				return res, fmt.Errorf("init goose version table: %w", err)
			}
		}
		// If the baseline is not yet recorded, record it without executing.
		ver, err := goose.GetDBVersionContext(ctx, d.SQL)
		if err != nil {
			return res, err
		}
		if ver < baselineVersion {
			if err := markBaselineApplied(ctx, d.SQL); err != nil {
				return res, fmt.Errorf("mark baseline applied: %w", err)
			}
			res.Adopted = true
		}
	}

	if err := goose.UpContext(ctx, d.SQL, "migrations"); err != nil {
		return res, fmt.Errorf("goose up: %w", err)
	}

	ver, err := goose.GetDBVersionContext(ctx, d.SQL)
	if err != nil {
		return res, err
	}
	res.Version = ver
	return res, nil
}

// markBaselineApplied inserts the baseline version row manually so goose skips
// executing 00000 against an already-populated database.
func markBaselineApplied(ctx context.Context, db *sql.DB) error {
	// goose_db_version columns: id, version_id, is_applied, tstamp
	_, err := db.ExecContext(ctx,
		`INSERT INTO goose_db_version (version_id, is_applied, tstamp) VALUES ($1, true, now())`,
		baselineVersion)
	return err
}

func tableExists(ctx context.Context, db *sql.DB, name string) (bool, error) {
	var exists bool
	err := db.QueryRowContext(ctx,
		`SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=$1)`,
		name).Scan(&exists)
	return exists, err
}

type gooseLogger struct{}

func (gooseLogger) Fatalf(format string, v ...any) { slog.Error(fmt.Sprintf(format, v...)) }
func (gooseLogger) Printf(format string, v ...any) {
	slog.Info(strings.TrimSpace(fmt.Sprintf(format, v...)))
}
