//go:build windows

package coreproc

// Windows 上 venv 的 Scripts\python.exe 是一个启动器，它会派生出真正持有
// 监听端口与数据库锁的解释器子进程。宿主持有的 PID 只指向启动器，因此仅凭
// Process.Kill 无法保证子进程一起退出；残留的子进程会继续持有权威状态，
// 使下一次启动因单实例保护而失败。
//
// 这里改用 Job Object：把启动器进程加入一个设置了 KILL_ON_JOB_CLOSE 的作业。
// 作业句柄被关闭时，Windows 会终止作业内的全部进程，包括派生出的解释器。
// 宿主被强制结束时，句柄由操作系统统一关闭，因此不会留下孤立核心。

import (
	"fmt"
	"sync"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	jobMu     sync.Mutex
	jobHandle windows.Handle
)

// attachToKillOnCloseJob 把指定进程加入"句柄关闭即终止"的作业。
// 返回的 release 用于核心正常退出后主动释放句柄。
func attachToKillOnCloseJob(pid int) (release func(), err error) {
	job, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return nil, fmt.Errorf("create job object: %w", err)
	}

	var info windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION
	info.BasicLimitInformation.LimitFlags = windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	if _, err := windows.SetInformationJobObject(
		job,
		windows.JobObjectExtendedLimitInformation,
		uintptr(unsafe.Pointer(&info)),
		uint32(unsafe.Sizeof(info)),
	); err != nil {
		_ = windows.CloseHandle(job)
		return nil, fmt.Errorf("configure job object: %w", err)
	}

	process, err := windows.OpenProcess(windows.PROCESS_SET_QUOTA|windows.PROCESS_TERMINATE, false, uint32(pid))
	if err != nil {
		_ = windows.CloseHandle(job)
		return nil, fmt.Errorf("open core process: %w", err)
	}
	defer windows.CloseHandle(process)

	if err := windows.AssignProcessToJobObject(job, process); err != nil {
		_ = windows.CloseHandle(job)
		return nil, fmt.Errorf("assign core process to job: %w", err)
	}

	jobMu.Lock()
	if jobHandle != 0 {
		// 上一次的作业已经随其核心退出，这里关闭以避免句柄泄漏。
		_ = windows.CloseHandle(jobHandle)
	}
	jobHandle = job
	jobMu.Unlock()

	var released sync.Once
	return func() {
		released.Do(func() {
			jobMu.Lock()
			defer jobMu.Unlock()
			if jobHandle == job {
				_ = windows.CloseHandle(job)
				jobHandle = 0
			} else {
				_ = windows.CloseHandle(job)
			}
		})
	}, nil
}
