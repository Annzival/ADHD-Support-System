package main

// Both processes explicitly use the same OS clock, not Go's private Time epoch.
type elapsedReading struct {
	Clock     string `json:"clock"`
	Ticks     int64  `json:"ticks"`
	Frequency int64  `json:"frequency"`
}
