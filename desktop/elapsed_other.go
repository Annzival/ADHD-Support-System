//go:build !linux && !windows

package main

func readElapsed() *elapsedReading { return nil }
