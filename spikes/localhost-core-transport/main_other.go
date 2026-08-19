//go:build !windows

package main

// The V-02 Wails host is deliberately exercised only on the Windows target.
// Linux phase A validates the Python Core test double and source contracts.
func main() {}
