import { EventEmitter } from 'events';
import {
  TradeEntry,
  TimeRangeQueryOptions,
  PointInTimeQueryOptions,
  TradeEntryCallback,
  StoreStats,
} from '../types.js';

/**
 * Bucket size in milliseconds (1 minute)
 */
const BUCKET_SIZE_MS = 60000;

/**
 * Time-bucketed store for efficient range queries and point lookups.
 * Uses 1-minute buckets with sorted arrays for O(log n) lookups within buckets.
 */
export class TimeSeriesStore extends EventEmitter {
  private buckets: Map<number, TradeEntry[]> = new Map();
  private totalCount: number = 0;
  private minTimestamp: number | null = null;
  private maxTimestamp: number | null = null;

  constructor() {
    super();
  }

  /**
   * Get the bucket key for a given timestamp
   */
  private getBucketKey(timestamp: number): number {
    return Math.floor(timestamp / BUCKET_SIZE_MS);
  }

  /**
   * Binary search to find insertion index in a sorted array
   * @returns The index where the entry should be inserted to maintain sort order
   */
  private findInsertIndex(bucket: TradeEntry[], entry: TradeEntry): number {
    let low = 0;
    let high = bucket.length;

    while (low < high) {
      const mid = Math.floor((low + high) / 2);
      if (bucket[mid].timestamp < entry.timestamp) {
        low = mid + 1;
      } else {
        high = mid;
      }
    }

    return low;
  }

  /**
   * Binary search to find the index of an entry at a specific timestamp
   * @returns The index of the entry, or -1 if not found
   */
  private findIndexAtTime(bucket: TradeEntry[], timestamp: number): number {
    let low = 0;
    let high = bucket.length - 1;

    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      if (bucket[mid].timestamp === timestamp) {
        return mid;
      } else if (bucket[mid].timestamp < timestamp) {
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }

    return -1;
  }

  /**
   * Binary search to find the first entry >= timestamp
   * @returns The index of the first entry >= timestamp, or bucket.length if none
   */
  private findFirstAtOrAfter(bucket: TradeEntry[], timestamp: number): number {
    let low = 0;
    let high = bucket.length;

    while (low < high) {
      const mid = Math.floor((low + high) / 2);
      if (bucket[mid].timestamp < timestamp) {
        low = mid + 1;
      } else {
        high = mid;
      }
    }

    return low;
  }

  /**
   * Insert a trade entry into the store
   * Time complexity: O(log n) for binary search + O(n) for array insertion
   * For high-throughput, consider using a different data structure or batching
   */
  insert(entry: TradeEntry): void {
    const bucketKey = this.getBucketKey(entry.timestamp);

    let bucket = this.buckets.get(bucketKey);
    if (!bucket) {
      bucket = [];
      this.buckets.set(bucketKey, bucket);
    }

    // Find the correct position to maintain sorted order
    const insertIndex = this.findInsertIndex(bucket, entry);
    bucket.splice(insertIndex, 0, entry);

    this.totalCount++;

    // Update min/max timestamps
    if (this.minTimestamp === null || entry.timestamp < this.minTimestamp) {
      this.minTimestamp = entry.timestamp;
    }
    if (this.maxTimestamp === null || entry.timestamp > this.maxTimestamp) {
      this.maxTimestamp = entry.timestamp;
    }

    // Emit event for real-time subscribers
    this.emit('entry', entry);
  }

  /**
   * Batch insert multiple entries for better performance
   */
  insertBatch(entries: TradeEntry[]): void {
    // Sort entries by timestamp first
    const sorted = [...entries].sort((a, b) => a.timestamp - b.timestamp);

    for (const entry of sorted) {
      const bucketKey = this.getBucketKey(entry.timestamp);

      let bucket = this.buckets.get(bucketKey);
      if (!bucket) {
        bucket = [];
        this.buckets.set(bucketKey, bucket);
      }

      // Since we're inserting in sorted order, we can append
      bucket.push(entry);

      this.totalCount++;

      if (this.minTimestamp === null || entry.timestamp < this.minTimestamp) {
        this.minTimestamp = entry.timestamp;
      }
      if (this.maxTimestamp === null || entry.timestamp > this.maxTimestamp) {
        this.maxTimestamp = entry.timestamp;
      }
    }

    // Emit batch event
    this.emit('batch', sorted);
  }

  /**
   * Query entries within a time range
   * Time complexity: O(k + n) where k = number of buckets, n = entries in range
   */
  getByTimeRange(options: TimeRangeQueryOptions): TradeEntry[] {
    const { start, end, source, side, limit } = options;
    const results: TradeEntry[] = [];

    const startBucket = this.getBucketKey(start);
    const endBucket = this.getBucketKey(end - 1); // -1 because end is exclusive

    for (let bucketKey = startBucket; bucketKey <= endBucket; bucketKey++) {
      const bucket = this.buckets.get(bucketKey);
      if (!bucket) continue;

      // For the start bucket, find the first entry >= start
      const startIndex = bucketKey === startBucket
        ? this.findFirstAtOrAfter(bucket, start)
        : 0;

      // For the end bucket, stop before entries >= end
      for (let i = startIndex; i < bucket.length; i++) {
        const entry = bucket[i];

        // Stop if we've passed the end time
        if (entry.timestamp >= end) break;

        // Apply filters
        if (source && entry.source !== source) continue;
        if (side && entry.side !== side) continue;

        results.push(entry);

        // Check limit
        if (limit && results.length >= limit) {
          return results;
        }
      }
    }

    return results;
  }

  /**
   * Get all entries at exactly the specified timestamp
   */
  getAtTime(timestamp: number): TradeEntry[] {
    const bucketKey = this.getBucketKey(timestamp);
    const bucket = this.buckets.get(bucketKey);

    if (!bucket) return [];

    const results: TradeEntry[] = [];
    const startIndex = this.findIndexAtTime(bucket, timestamp);

    if (startIndex === -1) return [];

    // Collect all entries with the same timestamp
    for (let i = startIndex; i < bucket.length && bucket[i].timestamp === timestamp; i++) {
      results.push(bucket[i]);
    }

    return results;
  }

  /**
   * Get the entry nearest to the specified timestamp
   * @param timestamp Target timestamp
   * @param tolerance Maximum distance from target (default: 60000ms = 1 minute)
   */
  getNearest(timestamp: number, tolerance: number = 60000): TradeEntry | null {
    const bucketKey = this.getBucketKey(timestamp);
    const bucket = this.buckets.get(bucketKey);

    // If we have the exact bucket, search within it
    if (bucket && bucket.length > 0) {
      const index = this.findFirstAtOrAfter(bucket, timestamp);

      // Check entry at or after timestamp
      const afterEntry = index < bucket.length ? bucket[index] : null;
      const beforeEntry = index > 0 ? bucket[index - 1] : null;

      let nearest: TradeEntry | null = null;
      let minDistance = Infinity;

      if (afterEntry && Math.abs(afterEntry.timestamp - timestamp) <= tolerance) {
        const dist = Math.abs(afterEntry.timestamp - timestamp);
        if (dist < minDistance) {
          minDistance = dist;
          nearest = afterEntry;
        }
      }

      if (beforeEntry && Math.abs(beforeEntry.timestamp - timestamp) <= tolerance) {
        const dist = Math.abs(beforeEntry.timestamp - timestamp);
        if (dist < minDistance) {
          nearest = beforeEntry;
        }
      }

      if (nearest) return nearest;
    }

    // If no entry found in the target bucket, check adjacent buckets
    const checkBuckets = [
      this.buckets.get(bucketKey - 1),
      this.buckets.get(bucketKey + 1),
    ];

    let nearest: TradeEntry | null = null;
    let minDistance = Infinity;

    for (const adjBucket of checkBuckets) {
      if (!adjBucket || adjBucket.length === 0) continue;

      // Get closest entry in this bucket
      const index = this.findFirstAtOrAfter(adjBucket, timestamp);

      const candidates: (TradeEntry | null)[] = [
        index < adjBucket.length ? adjBucket[index] : null,
        index > 0 ? adjBucket[index - 1] : null,
      ];

      for (const candidate of candidates) {
        if (!candidate) continue;

        const distance = Math.abs(candidate.timestamp - timestamp);
        if (distance <= tolerance && distance < minDistance) {
          minDistance = distance;
          nearest = candidate;
        }
      }
    }

    return nearest;
  }

  /**
   * Subscribe to real-time updates
   */
  subscribe(callback: TradeEntryCallback): () => void {
    this.on('entry', callback);
    return () => this.off('entry', callback);
  }

  /**
   * Subscribe to batch updates
   */
  subscribeBatch(callback: (entries: TradeEntry[]) => void): () => void {
    this.on('batch', callback);
    return () => this.off('batch', callback);
  }

  /**
   * Get statistics about the store
   */
  getStats(): StoreStats {
    // Estimate memory usage (rough approximation)
    // Each TradeEntry has ~5 fields, estimate ~100 bytes per entry
    const estimatedMemoryBytes = this.totalCount * 100;

    return {
      totalEntries: this.totalCount,
      bucketCount: this.buckets.size,
      earliestTimestamp: this.minTimestamp,
      latestTimestamp: this.maxTimestamp,
      estimatedMemoryBytes,
    };
  }

  /**
   * Clear all data from the store
   */
  clear(): void {
    this.buckets.clear();
    this.totalCount = 0;
    this.minTimestamp = null;
    this.maxTimestamp = null;
  }

  /**
   * Get the total count of entries
   */
  get size(): number {
    return this.totalCount;
  }

  /**
   * Check if the store is empty
   */
  get isEmpty(): boolean {
    return this.totalCount === 0;
  }
}