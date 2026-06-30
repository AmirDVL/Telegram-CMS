package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	queueWorker  = "arq:queue:worker"
	queueBot     = "arq:queue:bot"
	jobKeyPrefix = "arq:job:"
	// arq's default expires_extra_ms keeps the job payload ~1 day past its run.
	arqExpiresExtraMs = 86_400_000
)

// buildPublishJobBody produces the JSON job payload arq's serialize_job creates
// for `publish(post_id)` with the JSON serializer: {t, f, a, k, et}. job_try is
// null on first enqueue.
func buildPublishJobBody(postID, enqueueTimeMs int64) ([]byte, error) {
	return json.Marshal(map[string]any{
		"t":  nil,
		"f":  "publish",
		"a":  []int64{postID},
		"k":  map[string]any{},
		"et": enqueueTimeMs,
	})
}

func randJobID() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil // 32 hex chars, like uuid4().hex
}

// enqueuePublish writes an ARQ "publish" job to QUEUE_BOT exactly as
// shared.tasks.enqueue_publish does. It depends on the Python side using the
// JSON job serializer (see shared/tasks.py): the job body is
// json({t, f, a, k, et}) and the queue is a sorted set scored by run-time-ms.
// delay is the defer duration (0 = run now).
func (a *App) enqueuePublish(ctx context.Context, postID int64, delay time.Duration) error {
	jobID, err := randJobID()
	if err != nil {
		return err
	}
	enqueueTimeMs := time.Now().UnixMilli()
	deferMs := delay.Milliseconds()
	if deferMs < 0 {
		deferMs = 0
	}
	score := enqueueTimeMs + deferMs

	body, err := buildPublishJobBody(postID, enqueueTimeMs)
	if err != nil {
		return err
	}
	expiresMs := score - enqueueTimeMs + arqExpiresExtraMs

	pipe := a.rdb.TxPipeline()
	pipe.Set(ctx, jobKeyPrefix+jobID, body, time.Duration(expiresMs)*time.Millisecond)
	pipe.ZAdd(ctx, queueBot, redis.Z{Score: float64(score), Member: jobID})
	_, err = pipe.Exec(ctx)
	return err
}
