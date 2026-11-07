// Package crypto implements the exact at-rest credential encryption used by the
// Python backend so an existing production database remains readable after the
// Go cutover.
//
// The Python service encrypts secrets with `cryptography.fernet.Fernet`, keyed
// by the SHA-256 digest of the app `secret_key` (url-base64 encoded). Fernet is
// a well-defined wire format:
//
//	base64url( 0x80 || IV(16) || AES-128-CBC-PKCS7(ciphertext) || HMAC-SHA256(0x80||IV||ct) )
//
// with the HMAC key being the *second* 16 bytes of the 32-byte AES key
// (cryptography's AES-CBC + HMAC split). We reproduce it byte-for-byte so tokens
// written by Python decrypt here and vice versa.
package cryptoutil

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"strings"
	"time"
)

const (
	fernetVersion = 0x80
	tokenMagic    = "gAAAAA"
)

// Fernet derives the 32-byte signing/encryption key from the app secret the same
// way Python does: sha256(secret), then base64url (no padding).
func fernetKey(secret string) []byte {
	h := sha256.Sum256([]byte(secret))
	return h[:]
}

func b64urlRaw(b []byte) string {
	return base64.URLEncoding.EncodeToString(b)
}

func b64urlDecode(s string) ([]byte, error) {
	// Python's urlsafe_b64encode keeps '=' padding; RawURLEncoding rejects it,
	// so try both.
	if raw, err := base64.RawURLEncoding.DecodeString(s); err == nil {
		return raw, nil
	}
	return base64.URLEncoding.DecodeString(s)
}

// EncryptSecret produces a Fernet token (same format as Python's
// `encrypt_secret`). It returns a value beginning with "gAAAAA".
func EncryptSecret(plaintext, secret string) (string, error) {
	key := fernetKey(secret)

	iv := make([]byte, aes.BlockSize)
	if _, err := rand.Read(iv); err != nil {
		return "", err
	}

	block, err := aes.NewCipher(key[16:])
	if err != nil {
		return "", err
	}
	// Fernet wire layout: version(1) || timestamp(8, big-endian) || IV(16) ||
	// AES-128-CBC(PKCS7 plaintext) || HMAC-SHA256(previous bytes). The timestamp
	// is a header field, NOT part of the encrypted plaintext.
	ts := make([]byte, 8)
	now := uint64(time.Now().Unix())
	for i := 0; i < 8; i++ {
		ts[7-i] = byte(now >> (8 * i))
	}

	padded := pkcs7Pad([]byte(plaintext), aes.BlockSize)
	ciphertext := make([]byte, len(padded))
	cipher.NewCBCEncrypter(block, iv).CryptBlocks(ciphertext, padded)

	payload := make([]byte, 0, 1+len(ts)+len(iv)+len(ciphertext))
	payload = append(payload, fernetVersion)
	payload = append(payload, ts...)
	payload = append(payload, iv...)
	payload = append(payload, ciphertext...)

	// HMAC key is the second 16 bytes of the 32-byte key.
	mac := hmac.New(sha256.New, key[:16])
	mac.Write(payload)
	sig := mac.Sum(nil)

	payload = append(payload, sig...)
	return b64urlRaw(payload), nil
}

// DecryptSecret decrypts a Fernet token produced by Python's `encrypt_secret`.
// Values that are not Fernet tokens (no "gAAAAA" magic) are treated as legacy
// plaintext seeding, matching the Python fallback. A value that *is* a Fernet
// token but fails authentication is an integrity failure (fail closed).
func DecryptSecret(ciphertext, secret string) (string, error) {
	if !strings.HasPrefix(ciphertext, tokenMagic) {
		return ciphertext, nil
	}

	raw, err := b64urlDecode(ciphertext)
	if err != nil {
		return "", errors.New("invalid fernet token encoding")
	}
	if len(raw) < 1+aes.BlockSize+8+sha256.Size {
		return "", errors.New("fernet token too short")
	}

	sigStart := len(raw) - sha256.Size
	payload := raw[:sigStart]
	sig := raw[sigStart:]

	key := fernetKey(secret)
	mac := hmac.New(sha256.New, key[:16])
	mac.Write(payload)
	if !hmac.Equal(sig, mac.Sum(nil)) {
		return "", errors.New("fernet integrity check failed")
	}

	if payload[0] != fernetVersion {
		return "", errors.New("unsupported fernet version")
	}

	// version(1) || timestamp(8) || IV(16) || ciphertext
	const headerLen = 1 + 8 + aes.BlockSize
	if len(payload) < headerLen {
		return "", errors.New("fernet payload too short")
	}
	iv := payload[1+8 : headerLen]
	encrypted := payload[headerLen:]
	if len(encrypted)%aes.BlockSize != 0 || len(encrypted) == 0 {
		return "", errors.New("fernet ciphertext not block aligned")
	}

	block, err := aes.NewCipher(key[16:])
	if err != nil {
		return "", err
	}
	plain := make([]byte, len(encrypted))
	cipher.NewCBCDecrypter(block, iv).CryptBlocks(plain, encrypted)

	plain, err = pkcs7Unpad(plain)
	if err != nil {
		return "", err
	}
	return string(plain), nil
}

func pkcs7Pad(data []byte, blockSize int) []byte {
	padLen := blockSize - len(data)%blockSize
	out := make([]byte, len(data)+padLen)
	copy(out, data)
	for i := len(data); i < len(out); i++ {
		out[i] = byte(padLen)
	}
	return out
}

func pkcs7Unpad(data []byte) ([]byte, error) {
	if len(data) == 0 {
		return nil, errors.New("empty padding")
	}
	padLen := int(data[len(data)-1])
	if padLen == 0 || padLen > len(data) {
		return nil, errors.New("invalid padding")
	}
	for i := 0; i < padLen; i++ {
		if data[len(data)-1-i] != byte(padLen) {
			return nil, errors.New("invalid padding bytes")
		}
	}
	return data[:len(data)-padLen], nil
}
