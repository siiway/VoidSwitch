package core

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func GenerateVoidToken() string {
	b := make([]byte, 32)
	_, err := rand.Read(b)
	if err != nil {
		panic(fmt.Sprintf("security: failed to generate random bytes: %v", err))
	}
	return "vs-" + base64.RawURLEncoding.EncodeToString(b)
}

func HashToken(token string) string {
	h := sha256.Sum256([]byte(token))
	return hex.EncodeToString(h[:])
}

func TokenFingerprint(token string) string {
	h := HashToken(token)
	return h[len(h)-4:] + "\u2026" + h[:6]
}

func ConstantTimeEquals(a, b string) bool {
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}

func CreateSessionToken(secret string, subject string, extra map[string]any, ttlMinutes int) (string, error) {
	now := time.Now()
	claims := jwt.MapClaims{
		"iss": "voidswitch",
		"sub": subject,
		"iat": now.Unix(),
		"exp": now.Add(time.Duration(ttlMinutes) * time.Minute).Unix(),
	}
	for k, v := range extra {
		if k == "iss" || k == "sub" || k == "iat" || k == "exp" {
			continue
		}
		claims[k] = v
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString([]byte(secret))
}

func DecodeSessionToken(tokenString string, secret string) (map[string]any, error) {
	parsed, err := jwt.Parse(tokenString, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return []byte(secret), nil
	})
	if err != nil {
		return nil, err
	}
	if !parsed.Valid {
		return nil, errors.New("invalid session token")
	}
	claims, ok := parsed.Claims.(jwt.MapClaims)
	if !ok {
		return nil, errors.New("unexpected claims type")
	}
	result := make(map[string]any, len(claims))
	for k, v := range claims {
		result[k] = v
	}
	return result, nil
}

const fernetVersion byte = 0x80

func deriveKey(secret string) []byte {
	h := sha256.Sum256([]byte(secret))
	return h[:]
}

func EncryptSecret(plaintext string, secret string) (string, error) {
	key := deriveKey(secret)
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", fmt.Errorf("security: aes cipher init failed: %w", err)
	}

	iv := make([]byte, aes.BlockSize)
	if _, err := rand.Read(iv); err != nil {
		return "", fmt.Errorf("security: iv generation failed: %w", err)
	}

	padded := pkcs7Pad([]byte(plaintext), aes.BlockSize)
	ciphertext := make([]byte, len(padded))
	mode := cipher.NewCBCEncrypter(block, iv)
	mode.CryptBlocks(ciphertext, padded)

	payload := make([]byte, 0, 1+aes.BlockSize+len(ciphertext))
	payload = append(payload, fernetVersion)
	payload = append(payload, iv...)
	payload = append(payload, ciphertext...)

	mac := hmac.New(sha256.New, key)
	mac.Write(payload)
	sig := mac.Sum(nil)

	payload = append(payload, sig...)

	return base64.RawURLEncoding.EncodeToString(payload), nil
}

func DecryptSecret(ciphertext string, secret string) (string, error) {
	key := deriveKey(secret)

	raw, err := base64.RawURLEncoding.DecodeString(ciphertext)
	if err != nil {
		return ciphertext, nil
	}

	minLen := 1 + aes.BlockSize + sha256.Size
	if len(raw) < minLen {
		return ciphertext, nil
	}

	sigStart := len(raw) - sha256.Size
	payload := raw[:sigStart]
	sig := raw[sigStart:]

	mac := hmac.New(sha256.New, key)
	mac.Write(payload)
	expected := mac.Sum(nil)
	if !hmac.Equal(sig, expected) {
		return ciphertext, nil
	}

	if payload[0] != fernetVersion {
		return ciphertext, nil
	}

	iv := payload[1 : 1+aes.BlockSize]
	encrypted := payload[1+aes.BlockSize:]

	block, err := aes.NewCipher(key)
	if err != nil {
		return ciphertext, nil
	}

	if len(encrypted)%aes.BlockSize != 0 {
		return ciphertext, nil
	}

	mode := cipher.NewCBCDecrypter(block, iv)
	decrypted := make([]byte, len(encrypted))
	mode.CryptBlocks(decrypted, encrypted)

	plaintext, err := pkcs7Unpad(decrypted)
	if err != nil {
		return ciphertext, nil
	}

	return string(plaintext), nil
}

func pkcs7Pad(data []byte, blockSize int) []byte {
	padLen := blockSize - len(data)%blockSize
	padding := make([]byte, padLen)
	for i := range padding {
		padding[i] = byte(padLen)
	}
	return append(data, padding...)
}

func pkcs7Unpad(data []byte) ([]byte, error) {
	if len(data) == 0 {
		return nil, errors.New("pkcs7: empty data")
	}
	padLen := int(data[len(data)-1])
	if padLen > len(data) || padLen == 0 {
		return nil, errors.New("pkcs7: invalid padding")
	}
	for i := 0; i < padLen; i++ {
		if data[len(data)-1-i] != byte(padLen) {
			return nil, errors.New("pkcs7: invalid padding")
		}
	}
	return data[:len(data)-padLen], nil
}


