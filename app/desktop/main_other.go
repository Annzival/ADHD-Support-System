//go:build !windows

// 非 Windows 平台不承诺 v0.1 支持（ADR-0009/0011）；保留可编译桩用于开发期语法检查。
package main

import "log"

func main() {
	log.Fatal("执行支持 v0.1 仅支持 Windows 10 x64；请在 Windows 上运行桌面宿主。")
}
