import {
  TradeEntry,
  TimeRangeQueryOptions,
  PointInTimeQueryOptions,
  TradeEntryCallback,
  StoreStats,
} from '../types.js';
import { TimeSeriesStore } from '../store/TimeSeriesStore.js';

/**
 * Consumer interface for querying the time series data
 * Provides a clean API for async operations to access the data
 */
export class DataConsumer {
  private store: TimeSeriesStore;

  constructor(store: TimeSeriesStore) {
    this.store = store;
  }

  /**
   * Get all entries within a time range
   * @param start Start timestamp (inclusive) in milliseconds
   * @param end End timestamp (exclusive) in milliseconds
   * @param options Optional filters (source, side, limit)
   */
  getByTimeRange(
    start: number,
    end: number,
    options?: {
      source?: string;
      side?: 'buy' | 'sell';
      limit?: number;
    }
  ): TradeEntry[] {
    if (start >= end) {
      throw new Error('Start timestamp must be less than end timestamp');
    }

    return this.store.getByTimeRange({
      start,
      end,
      ...options,
    });
  }

  /**
   * Get all entries at exactly the specified timestamp
   * @param timestamp Unix timestamp in milliseconds
   */
  getAtTime(timestamp: number): TradeEntry[] {
    if (typeof timestamp !== 'number' || isNaN(timestamp)) {
      throw new Error('Timestamp must be a valid number');
    }

    return this.store.getAtTime(timestamp);
  }

  /**
   * Get the entry nearest to the specified timestamp
   * @param timestamp Target timestamp in milliseconds
   * @param tolerance Maximum distance from target in milliseconds (default: 60000)
   */
  getNearest(timestamp: number, tolerance?: number): TradeEntry | null {
    if (typeof timestamp !== 'number' || isNaN(timestamp)) {
      throw new Error('Timestamp must be a valid number');
    }

    return this.store.getNearest(timestamp, tolerance);
  }

  /**
   * Get entries at a specific timestamp with optional filtering
   */
  getAtTimeFiltered(
    timestamp: number,
    filters?: {
      source?: string;
      side?: 'buy' | 'sell';
    }
  ): TradeEntry[] {
    let entries = this.store.getAtTime(timestamp);

    if (filters?.source) {
      entries = entries.filter((e) => e.source === filters.source);
    }

    if (filters?.side) {
      entries = entries.filter((e) => e.side === filters.side);
    }

    return entries;
  }

  /**
   * Get the first entry before a given timestamp
   * @param timestamp The reference timestamp
   * @param lookbackMs How far back to look (default: 3600000 = 1 hour)
   */
  getFirstBefore(timestamp: number, lookbackMs: number = 3600000): TradeEntry | null {
    const entries = this.store.getByTimeRange({
      start: timestamp - lookbackMs,
      end: timestamp,
    });

    if (entries.length === 0) return null;

    // Return the last entry in the range (closest to timestamp)
    return entries[entries.length - 1];
  }

  /**
   * Get the first entry after a given timestamp
   * @param timestamp The reference timestamp
   * @param lookAheadMs How far ahead to look (default: 3600000 = 1 hour)
   */
  getFirstAfter(timestamp: number, lookAheadMs: number = 3600000): TradeEntry | null {
    const entries = this.store.getByTimeRange({
      start: timestamp + 1,
      end: timestamp + lookAheadMs,
      limit: 1,
    });

    return entries.length > 0 ? entries[0] : null;
  }

  /**
   * Get aggregated statistics for a time range
   */
  getAggregates(start: number, end: number): {
    count: number;
    buyCount: number;
    sellCount: number;
    totalVolume: number;
    buyVolume: number;
    sellVolume: number;
    avgPrice: number;
    minPrice: number;
    maxPrice: number;
  } {
    const entries = this.store.getByTimeRange({ start, end });

    if (entries.length === 0) {
      return {
        count: 0,
        buyCount: 0,
        sellCount: 0,
        totalVolume: 0,
        buyVolume: 0,
        sellVolume: 0,
        avgPrice: 0,
        minPrice: 0,
        maxPrice: 0,
      };
    }

    let buyCount = 0;
    let sellCount = 0;
    let totalVolume = 0;
    let buyVolume = 0;
    let sellVolume = 0;
    let priceSum = 0;
    let minPrice = Infinity;
    let maxPrice = -Infinity;

    for (const entry of entries) {
      if (entry.side === 'buy') {
        buyCount++;
        buyVolume += entry.size;
      } else {
        sellCount++;
        sellVolume += entry.size;
      }

      totalVolume += entry.size;
      priceSum += entry.price;
      minPrice = Math.min(minPrice, entry.price);
      maxPrice = Math.max(maxPrice, entry.price);
    }

    return {
      count: entries.length,
      buyCount,
      sellCount,
      totalVolume,
      buyVolume,
      sellVolume,
      avgPrice: priceSum / entries.length,
      minPrice,
      maxPrice,
    };
  }

  /**
   * Subscribe to real-time updates for new entries
   * @returns Unsubscribe function
   */
  subscribe(callback: TradeEntryCallback): () => void {
    return this.store.subscribe(callback);
  }

  /**
   * Subscribe to batch updates
   * @returns Unsubscribe function
   */
  subscribeBatch(callback: (entries: TradeEntry[]) => void): () => void {
    return this.store.subscribeBatch(callback);
  }

  /**
   * Get statistics about the data store
   */
  getStats(): StoreStats {
    return this.store.getStats();
  }

  /**
   * Get the total number of entries in the store
   */
  get size(): number {
    return this.store.size;
  }

  /**
   * Check if the store has any data
   */
  get isEmpty(): boolean {
    return this.store.isEmpty;
  }

  /**
   * Get the time range of data in the store
   */
  getTimeRange(): { start: number | null; end: number | null } {
    const stats = this.store.getStats();
    return {
      start: stats.earliestTimestamp,
      end: stats.latestTimestamp,
    };
  }

  /**
   * Batch query multiple time ranges
   * Useful for fetching data for multiple time windows in parallel
   */
  batchGetByTimeRange(
    ranges: Array<{ start: number; end: number; source?: string; side?: 'buy' | 'sell' }>
  ): Map<string, TradeEntry[]> {
    const results = new Map<string, TradeEntry[]>();

    for (const range of ranges) {
      const key = `${range.start}-${range.end}`;
      results.set(key, this.store.getByTimeRange(range));
    }

    return results;
  }
}