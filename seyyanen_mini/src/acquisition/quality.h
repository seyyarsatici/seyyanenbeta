#ifndef QUALITY_H
#define QUALITY_H

#include <Arduino.h>
#include <math.h>
#include "mini_types.h"
#include "mini_config.h"

// ==============================================================================
// DATA QUALITY & FRESHNESS EVALUATION ENGINE (PHASE M-4)
// ==============================================================================

class QualityEngine {
public:
    // Evaluate sample against PID physical bounds and acquisition status
    static QualityGrade evaluate(const MeasurementSample& sample, const PidMetadata* meta, uint64_t currentUs = 0);

    // Evaluate quality directly from status and decoded value
    static QualityGrade evaluateStatus(SampleStatus status, float value, const PidMetadata* meta);

    // Evaluate temporal freshness state based on last success timestamp
    static FreshnessState evaluateFreshness(uint64_t lastSuccessUs, uint64_t currentUs);

    // Physical sanity boundary check
    static bool isWithinPhysicalLimits(float value, float minVal, float maxVal);
};

#endif // QUALITY_H
