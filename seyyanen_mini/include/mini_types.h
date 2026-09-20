#ifndef MINI_TYPES_H
#define MINI_TYPES_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

// ==============================================================================
// SEYYANEN MINI - CORE TYPES & DATA STRUCTURES (PHASE M-4)
// ==============================================================================

// 1. Adapter Connection Lifecycle State (Phase M-2 Transport)
typedef enum {
    ADAPTER_STATE_DISCONNECTED = 0,
    ADAPTER_STATE_CONNECTING   = 1,
    ADAPTER_STATE_CONNECTED    = 2,
    ADAPTER_STATE_RECONNECTING = 3,
    ADAPTER_STATE_ERROR        = 4
} AdapterState;

// 2. Recognized Adapter Hardware Family
typedef enum {
    ADAPTER_BRAND_UNKNOWN = 0,
    ADAPTER_BRAND_ELM327  = 1,
    ADAPTER_BRAND_VLINKER = 2,
    ADAPTER_BRAND_OBDLINK = 3,
    ADAPTER_BRAND_STN     = 4
} AdapterBrand;

// 3. Transport-Level Error Classification
typedef enum {
    TRANSPORT_ERR_NONE                     = 0,
    TRANSPORT_ERR_BT_INIT_FAILED           = 1,
    TRANSPORT_ERR_TARGET_NOT_FOUND         = 2,
    TRANSPORT_ERR_SPP_CONNECT_FAILED       = 3,
    TRANSPORT_ERR_SPP_DISCONNECTED         = 4,
    TRANSPORT_ERR_TRANSACTION_TIMEOUT      = 5,
    TRANSPORT_ERR_INVALID_ADAPTER_RESPONSE = 6,
    TRANSPORT_ERR_REMOTE_REJECTED          = 7,
    TRANSPORT_ERR_SAFETY_BLOCKED           = 8,
    TRANSPORT_ERR_UNKNOWN                  = 9
} TransportError;

// 4. ELM327 Protocol Client State (Phase M-3)
typedef enum {
    ELM_STATE_UNINITIALIZED    = 0,
    ELM_STATE_INITIALIZING     = 1,
    ELM_STATE_READY            = 2,
    ELM_STATE_TIMEOUT          = 3,
    ELM_STATE_INVALID_RESPONSE = 4,
    ELM_STATE_TRANSPORT_ERROR  = 5
} Elm327State;

// 5. PID Scanner Discovery State (Phase M-3)
typedef enum {
    SCANNER_STATE_IDLE     = 0,
    SCANNER_STATE_SCANNING = 1,
    SCANNER_STATE_COMPLETE = 2,
    SCANNER_STATE_ERROR    = 3
} PidScannerState;

// 6. Acquisition Lifecycle State (Phase M-4)
typedef enum {
    ACQ_STATE_IDLE     = 0,
    ACQ_STATE_STARTING = 1,
    ACQ_STATE_RUNNING  = 2,
    ACQ_STATE_PAUSED   = 3,
    ACQ_STATE_STOPPING = 4,
    ACQ_STATE_STOPPED  = 5,
    ACQ_STATE_ERROR    = 6
} AcquisitionState;

// 7. Data Freshness State (Phase M-4)
typedef enum {
    FRESHNESS_FRESH       = 0, // < 0.6s
    FRESHNESS_AGING       = 1, // 0.6s .. 2.5s
    FRESHNESS_STALE       = 2, // >= 2.5s
    FRESHNESS_NEVER_VALID = 3  // No valid sample recorded yet
} FreshnessState;

// 8. Explicit Data Quality Grade (Phase M-4)
typedef enum {
    QUALITY_GRADE_GOOD            = 0,
    QUALITY_GRADE_DEGRADED        = 1,
    QUALITY_GRADE_STALE           = 2,
    QUALITY_GRADE_TIMEOUT         = 3,
    QUALITY_GRADE_NO_DATA         = 4,
    QUALITY_GRADE_MALFORMED       = 5,
    QUALITY_GRADE_TRANSPORT_ERROR = 6,
    QUALITY_GRADE_NOT_SUPPORTED   = 7,
    QUALITY_GRADE_INVALID         = 8
} QualityGrade;

// 9. Measurement Sample Status
typedef enum {
    SAMPLE_STATUS_VALID          = 0,
    SAMPLE_STATUS_NO_DATA        = 1,
    SAMPLE_STATUS_TIMEOUT        = 2,
    SAMPLE_STATUS_MALFORMED      = 3,
    SAMPLE_STATUS_NOT_SUPPORTED  = 4,
    SAMPLE_STATUS_TRANSPORT_ERR  = 5,
    SAMPLE_STATUS_SAFETY_BLOCKED = 6,
    SAMPLE_STATUS_PROTOCOL_ERR   = 7
} SampleStatus;

// 10. Individual Measurement Sample (Evidence + Interpreted)
typedef struct {
    char           session_id[36];       // Unique session identifier
    uint32_t       sequence;             // Monotonic sample sequence number
    uint64_t       timestamp_us;         // Monotonic microsecond timestamp
    uint16_t       pid;                  // e.g. 0x010C
    char           name[32];             // e.g. "Engine RPM"
    char           raw_response[64];     // Exact raw adapter response preserved
    uint8_t        normalized_bytes[8];  // Extracted Mode 01 payload bytes
    size_t         normalized_len;       // Payload byte count
    float          decoded_value;        // Interpreted numeric value
    char           unit[16];             // Engineering unit (e.g. "rpm", "degC")
    SampleStatus   status;               // Technical sample status
    QualityGrade   quality;              // Evaluated quality grade
    uint64_t       request_start_us;     // Microsecond timestamp of transmission
    uint64_t       response_timestamp_us;// Microsecond timestamp of receipt
    uint32_t       latency_us;           // Round-trip transport latency
    FreshnessState freshness;            // Freshness classification at capture
    uint32_t       target_interval_us;   // Configured target polling interval
    uint32_t       observed_interval_us; // Actual elapsed microseconds since prior sample of this PID
    uint32_t       scheduler_delay_us;   // Microseconds overdue when query began
    bool           is_deadline_miss;     // True if scheduler delay exceeded safety threshold
} MeasurementSample;

// 11. Acquisition Frame (Grouping of a scheduler cycle)
typedef struct {
    uint32_t frame_id;           // Monotonic cycle index
    uint64_t cycle_start_us;     // Cycle start timestamp
    uint64_t cycle_end_us;       // Cycle completion timestamp
    size_t   sample_count;       // Measurements taken in cycle
    uint16_t sample_pids[16];    // PIDs measured in this frame
} AcquisitionFrame;

// 12. Lightweight Live Signal Snapshot for Web UI
typedef struct {
    uint16_t       pid;
    char           name[24];
    float          value;             // Current observed value
    float          last_valid_value;  // Preserved across errors (NEVER zero fallback)
    char           unit[12];
    QualityGrade   quality;
    FreshnessState freshness;
    uint64_t       last_success_us;
    uint32_t       age_ms;
    uint32_t       latency_ms;
    uint32_t       target_interval_ms; // Configured target interval
    uint32_t       observed_interval_ms; // Realized interval between samples
    uint32_t       scheduler_delay_ms; // Actual scheduler delay
    uint32_t       deadline_misses;   // Accumulated missed deadlines
} LiveSignal;

// 13. Acquisition Runtime Performance Metrics
typedef struct {
    uint32_t total_requests;
    uint32_t successful_requests;
    uint32_t timeouts;
    uint32_t no_data_count;
    uint32_t malformed_count;
    uint32_t transport_errors;
    float    average_latency_ms;
    uint32_t last_latency_ms;
    float    requests_per_sec;
    size_t   active_pid_count;
} AcquisitionMetrics;

// 14. Full Live Snapshot (Thread-safe copy for Web presentation)
typedef struct {
    char               session_id[36];
    AcquisitionState   state;
    uint32_t           uptime_sec;
    LiveSignal         signals[16];
    size_t             signal_count;
    AcquisitionMetrics metrics;
} LiveSnapshot;

// 15. PID Decoder Function Signature
typedef float (*PidDecodeFunc)(const uint8_t* payload, size_t len, bool* ok);

// 16. PID Metadata Model
typedef struct {
    uint16_t      pid;                 // e.g. 0x010C
    uint8_t       mode;                // e.g. 0x01
    const char*   name;                // e.g. "Engine RPM"
    const char*   short_code;          // e.g. "RPM"
    const char*   unit;                // e.g. "rpm"
    const char*   description;         // Detailed description
    const char*   raw_formula;         // e.g. "((A*256)+B)/4"
    const char*   decoder_id;          // e.g. "DECODER_RPM"
    bool          supported;           // True if discovered via bitmap
    uint8_t       source_range;        // 0x00 for 0100, 0x20 for 0120
    uint8_t       bit_index;           // 1..32 in source bitmap
    uint8_t       priority;            // 0: Fast (120ms), 1: Med (350ms), 2: Slow (1200ms)
    uint32_t      poll_interval_ms;    // Configured polling interval
    PidDecodeFunc decode_fn;           // Decoder function
    float         min_valid;           // Lower bound sanity limit
    float         max_valid;           // Upper bound sanity limit
    float         last_smoke_value;    // Smoke test cached reading
    bool          has_smoke_value;     // Flag indicating smoke reading present
} PidMetadata;

// 17. Structured OBD-II Transaction Result Model
typedef struct {
    uint64_t     timestamp_us;
    char         request[16];
    uint8_t      mode;
    uint8_t      pid;
    char         raw_response[64];
    uint8_t      normalized_bytes[8];
    size_t       normalized_len;
    float        decoded_value;
    char         unit[16];
    SampleStatus status;
    char         error_msg[32];
    uint32_t     latency_ms;
} ObdResult;

// 18. Normalized Adapter Identity Structure
typedef struct {
    char         adapter_name[32];
    char         manufacturer[32];
    char         model[32];
    char         firmware[32];
    char         raw_identity[64];
    char         transport[20];
    char         remote_mac[20];
    AdapterBrand brand;
    bool         verified;
} AdapterIdentityInfo;

// 19. Transport Health Metrics
typedef struct {
    AdapterState   state;
    TransportError last_error;
    uint32_t       retry_count;
    uint32_t       current_backoff_ms;
    uint32_t       last_successful_comm_ms;
    uint32_t       connected_since_ms;
    uint32_t       last_response_timestamp_ms;
    uint32_t       last_latency_ms;
    uint32_t       rx_byte_count;
    uint32_t       tx_byte_count;
} TransportHealth;

// ==============================================================================
// String Helper Functions
// ==============================================================================

static inline const char* adapterStateToString(AdapterState s) {
    switch (s) {
        case ADAPTER_STATE_DISCONNECTED: return "DISCONNECTED";
        case ADAPTER_STATE_CONNECTING:   return "CONNECTING";
        case ADAPTER_STATE_CONNECTED:    return "CONNECTED";
        case ADAPTER_STATE_RECONNECTING: return "RECONNECTING";
        case ADAPTER_STATE_ERROR:        return "ERROR";
        default:                         return "UNKNOWN";
    }
}

static inline const char* adapterBrandToString(AdapterBrand b) {
    switch (b) {
        case ADAPTER_BRAND_ELM327:  return "ELM327";
        case ADAPTER_BRAND_VLINKER: return "VLINKER";
        case ADAPTER_BRAND_OBDLINK: return "OBDLINK";
        case ADAPTER_BRAND_STN:     return "STN";
        default:                    return "UNKNOWN";
    }
}

static inline const char* elm327StateToString(Elm327State s) {
    switch (s) {
        case ELM_STATE_UNINITIALIZED:    return "UNINITIALIZED";
        case ELM_STATE_INITIALIZING:     return "INITIALIZING";
        case ELM_STATE_READY:            return "READY";
        case ELM_STATE_TIMEOUT:          return "TIMEOUT";
        case ELM_STATE_INVALID_RESPONSE: return "INVALID_RESPONSE";
        case ELM_STATE_TRANSPORT_ERROR:  return "TRANSPORT_ERROR";
        default:                         return "UNKNOWN";
    }
}

static inline const char* scannerStateToString(PidScannerState s) {
    switch (s) {
        case SCANNER_STATE_IDLE:     return "IDLE";
        case SCANNER_STATE_SCANNING: return "SCANNING";
        case SCANNER_STATE_COMPLETE: return "COMPLETE";
        case SCANNER_STATE_ERROR:    return "ERROR";
        default:                     return "UNKNOWN";
    }
}

static inline const char* acquisitionStateToString(AcquisitionState s) {
    switch (s) {
        case ACQ_STATE_IDLE:     return "IDLE";
        case ACQ_STATE_STARTING: return "STARTING";
        case ACQ_STATE_RUNNING:  return "RUNNING";
        case ACQ_STATE_PAUSED:   return "PAUSED";
        case ACQ_STATE_STOPPING: return "STOPPING";
        case ACQ_STATE_STOPPED:  return "STOPPED";
        case ACQ_STATE_ERROR:    return "ERROR";
        default:                 return "UNKNOWN";
    }
}

static inline const char* freshnessStateToString(FreshnessState f) {
    switch (f) {
        case FRESHNESS_FRESH:       return "FRESH";
        case FRESHNESS_AGING:       return "AGING";
        case FRESHNESS_STALE:       return "STALE";
        case FRESHNESS_NEVER_VALID: return "NEVER_VALID";
        default:                    return "UNKNOWN";
    }
}

static inline const char* qualityGradeToString(QualityGrade q) {
    switch (q) {
        case QUALITY_GRADE_GOOD:            return "GOOD";
        case QUALITY_GRADE_DEGRADED:        return "DEGRADED";
        case QUALITY_GRADE_STALE:           return "STALE";
        case QUALITY_GRADE_TIMEOUT:         return "TIMEOUT";
        case QUALITY_GRADE_NO_DATA:         return "NO_DATA";
        case QUALITY_GRADE_MALFORMED:       return "MALFORMED";
        case QUALITY_GRADE_TRANSPORT_ERROR: return "TRANSPORT_ERROR";
        case QUALITY_GRADE_NOT_SUPPORTED:   return "NOT_SUPPORTED";
        default:                            return "INVALID";
    }
}

static inline const char* sampleStatusToString(SampleStatus s) {
    switch (s) {
        case SAMPLE_STATUS_VALID:          return "VALID";
        case SAMPLE_STATUS_NO_DATA:        return "NO_DATA";
        case SAMPLE_STATUS_TIMEOUT:        return "TIMEOUT";
        case SAMPLE_STATUS_MALFORMED:      return "MALFORMED";
        case SAMPLE_STATUS_NOT_SUPPORTED:  return "NOT_SUPPORTED";
        case SAMPLE_STATUS_TRANSPORT_ERR:  return "TRANSPORT_ERROR";
        case SAMPLE_STATUS_SAFETY_BLOCKED: return "SAFETY_BLOCKED";
        case SAMPLE_STATUS_PROTOCOL_ERR:   return "PROTOCOL_ERROR";
        default:                           return "UNKNOWN";
    }
}

// ==============================================================================
// PHASE M-5 - STORAGE & PERSISTENCE TYPES
// ==============================================================================

// 20. MicroSD Hardware & Filesystem Status
typedef enum {
    STORAGE_STATUS_IDLE             = 0,
    STORAGE_STATUS_READY            = 1,
    STORAGE_STATUS_NO_CARD          = 2,
    STORAGE_STATUS_READ_ONLY        = 3,
    STORAGE_STATUS_CARD_FULL        = 4,
    STORAGE_STATUS_WRITE_ERROR      = 5,
    STORAGE_STATUS_FILESYSTEM_ERROR = 6
} StorageStatus;

// 20b. Storage Engine Queue & Backpressure Health
typedef enum {
    STORAGE_HEALTH_OK           = 0,
    STORAGE_HEALTH_BACKPRESSURE = 1,
    STORAGE_HEALTH_OVERFLOW     = 2,
    STORAGE_HEALTH_WRITE_ERROR  = 3
} StorageHealth;

// 21. Persistent Session Recording State
typedef enum {
    SESSION_STATE_NO_SESSION             = 0,
    SESSION_STATE_STARTING               = 1,
    SESSION_STATE_ACTIVE                 = 2,
    SESSION_STATE_STOPPING               = 3,
    SESSION_STATE_FINALIZING             = 4,
    SESSION_STATE_COMPLETED              = 5,
    SESSION_STATE_RECOVERABLE_INCOMPLETE = 6,
    SESSION_STATE_ERROR                  = 7
} SessionState;

// 22. MicroSD Physical Storage Information
typedef struct {
    char          card_type[16];      // e.g. "SDHC", "SDSC"
    uint64_t      total_bytes;        // Total card capacity in bytes
    uint64_t      free_bytes;         // Available free space in bytes
    bool          card_present;       // Card detected in slot
    bool          is_mounted;         // FAT filesystem mounted successfully
    StorageStatus status;             // Current storage health status
} StorageInfo;

// 23. MicroSD Logging Performance Metrics
typedef struct {
    uint32_t      samples_written;         // Rows committed to SD
    uint32_t      samples_pending;         // Rows currently in write buffer
    uint32_t      samples_dropped;         // Rows dropped due to buffer overrun / SD error
    uint32_t      write_errors;            // SD write failure events
    uint32_t      flush_count;             // Successful flush calls
    // Hardening Observability Additions:
    uint32_t      queue_depth;             // Current samples in decoupled storage queue
    uint32_t      queue_high_water_mark;   // Maximum samples in queue observed
    uint32_t      backpressure_events;     // Occurrences where queue reached backpressure threshold
    uint32_t      last_write_latency_us;   // Microseconds taken by last physical write
    uint32_t      last_flush_latency_us;   // Microseconds taken by last physical flush
    StorageHealth health_state;            // STORAGE_OK, STORAGE_BACKPRESSURE, etc.
} StorageMetrics;

// 24. Session Context Metadata (For PC Seyyanen Import)
typedef struct {
    char          session_id[36];              // e.g. "MINI-20260920-223411-001"
    uint64_t      start_timestamp_us;          // Monotonic start timestamp
    uint64_t      end_timestamp_us;            // Monotonic end timestamp
    char          start_wall_time[32];         // Optional ISO8601 wall time or fallback
    char          end_wall_time[32];           // Optional ISO8601 wall time or fallback
    uint64_t      session_start_monotonic_us;  // Monotonic reference for wall-clock projection
    char          session_start_wall_clock[32];// Wall-clock reference if synchronized
    char          firmware_version[16];        // e.g. "1.0.0"
    char          mini_version[16];            // e.g. "M-5"
    char          adapter_name[32];            // e.g. "vLinker MC+ 2.2"
    char          adapter_model[32];           // e.g. "vLinker MC"
    char          adapter_firmware[32];        // e.g. "v2.2"
    char          adapter_raw_identity[64];    // Raw ATI string
    char          transport_medium[16];        // e.g. "BLUETOOTH_SPP"
    char          protocol[32];                // e.g. "ISO 15765-4 (CAN 11/500)"
    char          vehicle_context_status[16];  // Strictly "UNKNOWN" if no VIN
    size_t        supported_pid_count;         // Number of PIDs in session
    uint32_t      sample_count;                // Total recorded samples
    uint32_t      frame_count;                 // Total recorded frames
    uint32_t      error_count;                 // Total failed queries
    SessionState  session_state;               // ACTIVE -> COMPLETED / RECOVERABLE_INCOMPLETE
} SessionMetadata;

// 25. Lightweight Session Summary for Directory Listing
typedef struct {
    char         session_id[36];
    char         folder_path[64];
    uint64_t     start_timestamp_us;
    uint64_t     end_timestamp_us;
    uint32_t     sample_count;
    uint64_t     size_bytes;
    SessionState state;
} SessionSummary;

// 26. Unscheduled PID Explanation
typedef enum {
    UNSCHEDULED_REASON_NONE              = 0,
    UNSCHEDULED_REASON_EXCEEDED_CAPACITY = 1,
    UNSCHEDULED_REASON_UNSUPPORTED       = 2,
    UNSCHEDULED_REASON_PAUSED            = 3,
    UNSCHEDULED_REASON_USER_DISABLED     = 4
} UnscheduledReason;

typedef struct {
    uint16_t          pid;
    char              name[32];
    UnscheduledReason reason;
} UnscheduledPidInfo;

static inline const char* storageStatusToString(StorageStatus s) {
    switch (s) {
        case STORAGE_STATUS_IDLE:             return "IDLE";
        case STORAGE_STATUS_READY:            return "READY";
        case STORAGE_STATUS_NO_CARD:          return "NO_CARD";
        case STORAGE_STATUS_READ_ONLY:        return "READ_ONLY";
        case STORAGE_STATUS_CARD_FULL:        return "CARD_FULL";
        case STORAGE_STATUS_WRITE_ERROR:      return "WRITE_ERROR";
        case STORAGE_STATUS_FILESYSTEM_ERROR: return "FILESYSTEM_ERROR";
        default:                              return "UNKNOWN";
    }
}

static inline const char* storageHealthToString(StorageHealth h) {
    switch (h) {
        case STORAGE_HEALTH_OK:           return "STORAGE_OK";
        case STORAGE_HEALTH_BACKPRESSURE: return "STORAGE_BACKPRESSURE";
        case STORAGE_HEALTH_OVERFLOW:     return "STORAGE_OVERFLOW";
        case STORAGE_HEALTH_WRITE_ERROR:  return "STORAGE_WRITE_ERROR";
        default:                          return "UNKNOWN";
    }
}

static inline const char* unscheduledReasonToString(UnscheduledReason r) {
    switch (r) {
        case UNSCHEDULED_REASON_EXCEEDED_CAPACITY: return "EXCEEDED_SCHEDULER_CAPACITY";
        case UNSCHEDULED_REASON_UNSUPPORTED:       return "UNSUPPORTED";
        case UNSCHEDULED_REASON_PAUSED:            return "PAUSED";
        case UNSCHEDULED_REASON_USER_DISABLED:     return "USER_DISABLED";
        default:                                   return "NONE";
    }
}

static inline const char* sessionStateToString(SessionState s) {
    switch (s) {
        case SESSION_STATE_NO_SESSION:             return "NO_SESSION";
        case SESSION_STATE_STARTING:               return "STARTING";
        case SESSION_STATE_ACTIVE:                 return "ACTIVE";
        case SESSION_STATE_STOPPING:               return "STOPPING";
        case SESSION_STATE_FINALIZING:             return "FINALIZING";
        case SESSION_STATE_COMPLETED:              return "COMPLETED";
        case SESSION_STATE_RECOVERABLE_INCOMPLETE: return "RECOVERABLE_INCOMPLETE";
        case SESSION_STATE_ERROR:                  return "ERROR";
        default:                                   return "UNKNOWN";
    }
}

#endif // MINI_TYPES_H
