# Multi-stage build → tiny static binary on distroless. Replaces the heavy
# python:3.12-slim + uvicorn + FastAPI + SQLAlchemy image for the back-office API.
FROM golang:1.26-alpine AS build
WORKDIR /src
ENV CGO_ENABLED=0 GOOS=linux

# Cache module downloads against the committed go.mod/go.sum.
COPY go.mod go.sum ./
RUN go mod download

COPY *.go ./
RUN go build -ldflags="-s -w" -o /out/api .

FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /
COPY --from=build /out/api /api
EXPOSE 8000
USER nonroot:nonroot
ENTRYPOINT ["/api"]
