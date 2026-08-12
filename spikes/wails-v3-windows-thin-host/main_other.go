//go:build !windows

package main

// The actual Wails host intentionally builds only on the Windows target. The
// platform-neutral supervisor is tested from Linux in phase A; Windows UI
// behavior is reserved for the phase B evidence run.
func main() {}
