//go:build !windows

package main

// The real thin host is deliberately exercised only on the Windows target.
// Linux phase A validates the synthetic Core and source contracts.
func main() {}
