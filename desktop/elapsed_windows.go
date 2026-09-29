package main

import (
	"syscall"
	"unsafe"
)

var timingKernel = syscall.NewLazyDLL("kernel32.dll")
var queryCounter = timingKernel.NewProc("QueryPerformanceCounter")
var queryFrequency = timingKernel.NewProc("QueryPerformanceFrequency")

func readElapsed() *elapsedReading {
	var counter, frequency int64
	if queryCounter.Find() != nil || queryFrequency.Find() != nil {
		return nil
	}
	ok, _, _ := queryFrequency.Call(uintptr(unsafe.Pointer(&frequency)))
	if ok == 0 || frequency <= 0 {
		return nil
	}
	ok, _, _ = queryCounter.Call(uintptr(unsafe.Pointer(&counter)))
	if ok == 0 || counter < 0 {
		return nil
	}
	return &elapsedReading{Clock: "windows_qpc_v1", Ticks: counter, Frequency: frequency}
}
