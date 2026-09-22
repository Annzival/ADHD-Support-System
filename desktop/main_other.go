//go:build !windows

package main

func main() { panic("The desktop client is validated only on Windows 10 22H2 x64") }
