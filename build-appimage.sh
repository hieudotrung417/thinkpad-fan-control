#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
IMAGE_NAME=thinkpad-fan-control-appimage-builder
APP_VERSION=${VERSION:-1.0.0}

mkdir -p "$PROJECT_DIR/dist"

docker build \
    --build-arg "APP_VERSION=$APP_VERSION" \
    --file "$PROJECT_DIR/packaging/appimage/Dockerfile" \
    --tag "$IMAGE_NAME" \
    "$PROJECT_DIR"

docker run --rm \
    --user "$(id -u):$(id -g)" \
    --volume "$PROJECT_DIR/dist:/output" \
    "$IMAGE_NAME"

echo "Built: $PROJECT_DIR/dist/ThinkPad_Fan_Control-x86_64.AppImage"
