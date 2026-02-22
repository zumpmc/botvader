/**
 * Core type definitions for the S3 Data Stream Service
 */

/**
 * A single trade entry from the data stream
 */
export interface TradeEntry {
  /** Unix timestamp in milliseconds */
  timestamp: number;
  /** Trade price */
  price: number;
  /** Trade size/volume */
  size: number;
  /** Trade side: buy or sell */
  side: 'buy' | 'sell';
  /** Source identifier (exchange, data provider, etc.) */
  source: string;
}

/**
 * Options for time range queries
 */
export interface TimeRangeQueryOptions {
  /** Start timestamp (inclusive) in milliseconds */
  start: number;
  /** End timestamp (exclusive) in milliseconds */
  end: number;
  /** Optional filter by source */
  source?: string;
  /** Optional filter by side */
  side?: 'buy' | 'sell';
  /** Maximum number of results to return */
  limit?: number;
}

/**
 * Options for point-in-time lookups
 */
export interface PointInTimeQueryOptions {
  /** Target timestamp in milliseconds */
  timestamp: number;
  /** Tolerance in milliseconds for nearest lookup (default: 60000 = 1 minute) */
  tolerance?: number;
}

/**
 * Callback type for real-time updates
 */
export type TradeEntryCallback = (entry: TradeEntry) => void;

/**
 * Statistics about the store
 */
export interface StoreStats {
  /** Total number of entries */
  totalEntries: number;
  /** Number of time buckets */
  bucketCount: number;
  /** Earliest timestamp in the store */
  earliestTimestamp: number | null;
  /** Latest timestamp in the store */
  latestTimestamp: number | null;
  /** Estimated memory usage in bytes */
  estimatedMemoryBytes: number;
}

/**
 * Configuration for S3 ingestion
 */
export interface S3IngestConfig {
  /** S3 bucket name */
  bucket: string;
  /** Key prefix for filtering objects */
  prefix?: string;
  /** AWS region */
  region?: string;
  /** SQS queue URL for S3 event notifications (optional) */
  sqsQueueUrl?: string;
  /** Polling interval in milliseconds (if not using SQS) */
  pollingInterval?: number;
}

/**
 * Result of loading data from S3
 */
export interface LoadResult {
  /** Number of files processed */
  filesProcessed: number;
  /** Number of entries loaded */
  entriesLoaded: number;
  /** Any errors encountered */
  errors: Array<{ key: string; error: string }>;
}