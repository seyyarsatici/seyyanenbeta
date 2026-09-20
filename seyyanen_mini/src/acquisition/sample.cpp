#include "sample.h"
#include <string.h>

SampleRingBuffer::SampleRingBuffer(size_t capacity)
    : _capacity(capacity),
      _head(0),
      _tail(0),
      _count(0),
      _totalPushed(0) {
    if (_capacity == 0) _capacity = 128;
    _buffer = new MeasurementSample[_capacity];
    _mutex = xSemaphoreCreateMutex();
}

SampleRingBuffer::~SampleRingBuffer() {
    if (_mutex) {
        vSemaphoreDelete(_mutex);
    }
    delete[] _buffer;
}

void SampleRingBuffer::push(const MeasurementSample& sample) {
    if (!_buffer) return;

    if (_mutex && xSemaphoreTake(_mutex, pdMS_TO_TICKS(40)) == pdTRUE) {
        _buffer[_head] = sample;
        _head = (_head + 1) % _capacity;

        if (_count < _capacity) {
            _count++;
        } else {
            // Buffer full: advance tail, evicting oldest
            _tail = (_tail + 1) % _capacity;
        }
        _totalPushed++;

        xSemaphoreGive(_mutex);
    }
}

bool SampleRingBuffer::getLatest(uint16_t pid, MeasurementSample& outSample) const {
    if (!_buffer || _count == 0) return false;

    bool found = false;
    if (_mutex && xSemaphoreTake(_mutex, pdMS_TO_TICKS(40)) == pdTRUE) {
        for (size_t i = 0; i < _count; ++i) {
            size_t idx = (_head + _capacity - 1 - i) % _capacity;
            if (_buffer[idx].pid == pid) {
                outSample = _buffer[idx];
                found = true;
                break;
            }
        }
        xSemaphoreGive(_mutex);
    }
    return found;
}

bool SampleRingBuffer::getLatestAny(MeasurementSample& outSample) const {
    if (!_buffer || _count == 0) return false;

    bool found = false;
    if (_mutex && xSemaphoreTake(_mutex, pdMS_TO_TICKS(40)) == pdTRUE) {
        size_t idx = (_head + _capacity - 1) % _capacity;
        outSample = _buffer[idx];
        found = true;
        xSemaphoreGive(_mutex);
    }
    return found;
}

size_t SampleRingBuffer::getRecent(MeasurementSample* dest, size_t maxCount) const {
    if (!_buffer || !dest || maxCount == 0 || _count == 0) return 0;

    size_t copied = 0;
    if (_mutex && xSemaphoreTake(_mutex, pdMS_TO_TICKS(40)) == pdTRUE) {
        size_t limit = (_count < maxCount) ? _count : maxCount;
        for (size_t i = 0; i < limit; ++i) {
            size_t idx = (_head + _capacity - 1 - i) % _capacity;
            dest[i] = _buffer[idx];
            copied++;
        }
        xSemaphoreGive(_mutex);
    }
    return copied;
}

size_t SampleRingBuffer::getSince(uint64_t timestampUs, MeasurementSample* dest, size_t maxCount) const {
    if (!_buffer || !dest || maxCount == 0 || _count == 0) return 0;

    size_t copied = 0;
    if (_mutex && xSemaphoreTake(_mutex, pdMS_TO_TICKS(40)) == pdTRUE) {
        for (size_t i = 0; i < _count && copied < maxCount; ++i) {
            size_t idx = (_tail + i) % _capacity;
            if (_buffer[idx].timestamp_us >= timestampUs) {
                dest[copied++] = _buffer[idx];
            }
        }
        xSemaphoreGive(_mutex);
    }
    return copied;
}

size_t SampleRingBuffer::size() const {
    return _count;
}

size_t SampleRingBuffer::capacity() const {
    return _capacity;
}

uint32_t SampleRingBuffer::totalPushed() const {
    return _totalPushed;
}

void SampleRingBuffer::clear() {
    if (_mutex && xSemaphoreTake(_mutex, pdMS_TO_TICKS(40)) == pdTRUE) {
        _head = 0;
        _tail = 0;
        _count = 0;
        xSemaphoreGive(_mutex);
    }
}
