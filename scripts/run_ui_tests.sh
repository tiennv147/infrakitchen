#!/usr/bin/env sh
set -e
cd ui/frontend-lib
yarn type-check:test
yarn test:coverage
