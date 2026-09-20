#ifndef SAMPLE_H
#define SAMPLE_H

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "mini_types.h"
#include "mini_config.h"

// ==============================================================================
// BOUNDED RUNTIME RING BUFFER FOR MEASUREMENT SAMPLES (PHASE M-4)
// ==============================================================================

class SampleRingBuffer {
public:
    explicit SampleRingBuffer(size_t capacity = SEYYANEN_RING_BUFFER_SIZE);
    ~SampleRingBuffer();

    // Push new sample (overwrites oldest when full)
    void push(const MeasurementSample& sample);

    // Query latest sample for a specific PID
    bool getLatest(uint16_t pid, MeasurementSample& outSample) const;

    // Query most recent sample overall
    bool getLatestAny(MeasurementSample& outSample) const;

    // Copy up to maxCount recent samples into destination array
    size_t getRecent(MeasurementSample* dest, size_t maxCount) const;

    // Retrieve samples captured after a given monotonic microsecond timestamp
    size_t getSince(uint64_t timestampUs, MeasurementSample* dest, size_t maxCount) const;

    // Buffer state
    size_t   size() const;
    size_t   capacity() const;
    uint32_t totalPushed() const;
    void     clear();

private:
    MeasurementSample* _buffer;
    size_t             _capacity;
    size_t             _head;
    size_t             _tail;
    size_t             _count;
    uint32_t           _totalPushed;
    SemaphoreHandle_t  _mutex;
};

#endif // SAMPLE_H
