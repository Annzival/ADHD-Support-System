package main

import "golang.org/x/sys/unix"

func readElapsed() *elapsedReading {
	var ts unix.Timespec
	if unix.ClockGettime(unix.CLOCK_BOOTTIME, &ts) != nil {
		return nil
	}
	return &elapsedReading{Clock: "linux_boottime_v1", Ticks: ts.Nano(), Frequency: 1000000000}
}
