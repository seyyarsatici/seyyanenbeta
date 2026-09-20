#include "quality.h"

bool QualityEngine::isWithinPhysicalLimits(float value, float minVal, float maxVal) {
    if (isnan(value) || isinf(value)) return false;
    if (minVal >= maxVal) return true; // Bounds not enforced
    return (value >= minVal && value <= maxVal);
}

QualityGrade QualityEngine::evaluateStatus(SampleStatus status, float value, const PidMetadata* meta) {
    switch (status) {
        case SAMPLE_STATUS_VALID:
            if (isnan(value) || isinf(value)) {
                return QUALITY_GRADE_MALFORMED;
            }
            if (meta != NULL && !isWithinPhysicalLimits(value, meta->min_valid, meta->max_valid)) {
                return QUALITY_GRADE_DEGRADED;
            }
            return QUALITY_GRADE_GOOD;

        case SAMPLE_STATUS_TIMEOUT:
            return QUALITY_GRADE_TIMEOUT;

        case SAMPLE_STATUS_NO_DATA:
            return QUALITY_GRADE_NO_DATA;

        case SAMPLE_STATUS_MALFORMED:
        case SAMPLE_STATUS_PROTOCOL_ERR:
            return QUALITY_GRADE_MALFORMED;

        case SAMPLE_STATUS_TRANSPORT_ERR:
            return QUALITY_GRADE_TRANSPORT_ERROR;

        case SAMPLE_STATUS_NOT_SUPPORTED:
            return QUALITY_GRADE_NOT_SUPPORTED;

        default:
            return QUALITY_GRADE_INVALID;
    }
}

QualityGrade QualityEngine::evaluate(const MeasurementSample& sample, const PidMetadata* meta, uint64_t currentUs) {
    QualityGrade base = evaluateStatus(sample.status, sample.decoded_value, meta);

    // If base quality is GOOD, check if it has decayed temporally
    if (base == QUALITY_GRADE_GOOD && currentUs > 0 && sample.timestamp_us > 0) {
        uint64_t ageUs = (currentUs > sample.timestamp_us) ? (currentUs - sample.timestamp_us) : 0;
        if (ageUs >= SEYYANEN_STALE_THRESHOLD_US) {
            return QUALITY_GRADE_STALE;
        }
    }

    return base;
}

FreshnessState QualityEngine::evaluateFreshness(uint64_t lastSuccessUs, uint64_t currentUs) {
    if (lastSuccessUs == 0) {
        return FRESHNESS_NEVER_VALID;
    }

    uint64_t ageUs = (currentUs > lastSuccessUs) ? (currentUs - lastSuccessUs) : 0;

    if (ageUs < SEYYANEN_FRESH_THRESHOLD_US) {
        return FRESHNESS_FRESH;
    } else if (ageUs < SEYYANEN_AGING_THRESHOLD_US) {
        return FRESHNESS_AGING;
    } else {
        return FRESHNESS_STALE;
    }
}
