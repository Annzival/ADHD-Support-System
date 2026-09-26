//go:build windows

package main

import (
	"golang.org/x/sys/windows/registry"
	"os"
	"strings"
	"syscall"
)

// Device setup only: persist the exact host invocation in this user's Run key.
// It neither opens the Core database nor changes any execution state.
func setAutostart(enabled bool) error {
	key, _, err := registry.CreateKey(registry.CURRENT_USER, `Software\Microsoft\Windows\CurrentVersion\Run`, registry.SET_VALUE)
	if err != nil {
		return err
	}
	defer key.Close()
	const name = "ADHDSupportI02"
	if !enabled {
		err = key.DeleteValue(name)
		if err == registry.ErrNotExist {
			return nil
		}
		return err
	}
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	args := append([]string{executable}, os.Args[1:]...)
	for i, arg := range args {
		args[i] = syscall.EscapeArg(arg)
	}
	return key.SetStringValue(name, strings.Join(args, " "))
}
