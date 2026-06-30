package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// transformResult mirrors shared.transform.TransformResult.
type transformResult struct {
	Text             string
	Model            string
	PromptTokens     int
	CompletionTokens int
	LatencyMs        int
}

// buildSystemPrompt mirrors shared.transform._build_system_prompt.
func buildSystemPrompt(mode, targetLang, tonePrompt, customPrompt string) string {
	switch mode {
	case "translate":
		lang := targetLang
		if lang == "" {
			lang = "Persian"
		}
		return fmt.Sprintf("You are a professional translator. Translate the following message "+
			"into %s. Preserve the original formatting, line breaks, and any markdown/HTML tags. "+
			"Do NOT add any commentary or explanation — return only the translated text.", lang)
	case "summarize":
		return "You are a professional editor. Summarize the following message into concise " +
			"bullet points. Keep the key facts, strip opinion and filler. Use the same language " +
			"as the original unless instructed otherwise. Return only the bullet-point summary, no preamble."
	case "retone":
		tone := tonePrompt
		if tone == "" {
			tone = "professional and concise"
		}
		return fmt.Sprintf("You are a professional copywriter. Rewrite the following message to "+
			"match this tone/style: %s. Preserve all factual information but adjust the language, "+
			"formality, and voice accordingly. Return only the rewritten text.", tone)
	case "custom":
		if customPrompt != "" {
			return customPrompt
		}
		return "You are a helpful assistant. Process the text below."
	default:
		return ""
	}
}

// transformText mirrors shared.transform.transform_text using the OpenAI-
// compatible chat-completions API. Used only by the /ai/test endpoint.
func (a *App) transformText(ctx context.Context, text, mode, targetLang, tonePrompt, customPrompt string) (*transformResult, error) {
	if mode == "off" {
		return &transformResult{Text: text, Model: "none"}, nil
	}
	if a.cfg.AIAPIKey == "" {
		return nil, fmt.Errorf("AI_API_KEY is not configured")
	}

	system := buildSystemPrompt(mode, targetLang, tonePrompt, customPrompt)
	reqBody, _ := json.Marshal(map[string]any{
		"model": a.cfg.AIModel,
		"messages": []map[string]string{
			{"role": "system", "content": system},
			{"role": "user", "content": text},
		},
		"max_tokens":  a.cfg.AIMaxTokens,
		"temperature": 0.3,
	})
	url := strings.TrimRight(a.cfg.AIProviderURL, "/") + "/chat/completions"

	cctx, cancel := context.WithTimeout(ctx, time.Duration(a.cfg.AITimeoutSeconds)*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(cctx, http.MethodPost, url, bytes.NewReader(reqBody))
	if err != nil {
		return nil, fmt.Errorf("LLM API call failed: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+a.cfg.AIAPIKey)
	req.Header.Set("Content-Type", "application/json")

	t0 := time.Now()
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("LLM API call failed: %w", err)
	}
	defer resp.Body.Close()
	latency := int(time.Since(t0).Milliseconds())
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("LLM API call failed: status %d", resp.StatusCode)
	}

	var parsed struct {
		Model   string `json:"model"`
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Usage struct {
			PromptTokens     int `json:"prompt_tokens"`
			CompletionTokens int `json:"completion_tokens"`
		} `json:"usage"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return nil, fmt.Errorf("LLM API call failed: %w", err)
	}
	if len(parsed.Choices) == 0 || strings.TrimSpace(parsed.Choices[0].Message.Content) == "" {
		return nil, fmt.Errorf("LLM returned an empty response")
	}
	model := parsed.Model
	if model == "" {
		model = a.cfg.AIModel
	}
	return &transformResult{
		Text:             strings.TrimSpace(parsed.Choices[0].Message.Content),
		Model:            model,
		PromptTokens:     parsed.Usage.PromptTokens,
		CompletionTokens: parsed.Usage.CompletionTokens,
		LatencyMs:        latency,
	}, nil
}
