//go:build !windows

package coreproc

// v0.1 只承诺 Windows 10 22H2 x64（ADR-0011）。非 Windows 构建不提供
// 进程树清理，仅保证接口一致，以便交叉编译与静态检查通过。
func attachToKillOnCloseJob(pid int) (release func(), err error) {
	_ = pid
	return func() {}, nil
}
