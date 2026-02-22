// Re-export types
export {
  TradeEntry,
  TimeRangeQueryOptions,
  PointInTimeQueryOptions,
  TradeEntryCallback,
  StoreStats,
  S3IngestConfig,
  LoadResult,
} from './types.js';

// Re-export classes
export { TimeSeriesStore } from './store/TimeSeriesStore.js';
export { S3Ingester } from './ingestion/S3Ingester.js';
export { DataConsumer } from './consumer/DataConsumer.js';

import { TimeSeriesStore } from './store/TimeSeriesStore.js';
import { S3Ingester } from './ingestion/S3Ingester.js';
import { DataConsumer } from './consumer/DataConsumer.js';
import { S3IngestConfig, TradeEntry } from './types.js';

/**
 * Options for creating the data stream service
 */
export interface DataStreamOptions {
  /** S3 configuration for data ingestion */
  s3Config: S3IngestConfig;
  /** Whether to load initial data on startup (default: true) */
  loadInitialData?: boolean;
  /** Whether to start watching for new files (default: true) */
  startWatching?: boolean;
}

/**
 * The main data stream service that combines all components
 */
export interface DataStreamService {
  /** The time series store */
  store: TimeSeriesStore;
  /** The S3 ingester */
  ingester: S3Ingester;
  /** The consumer API for queries */
  consumer: DataConsumer;
  /** Stop watching for new data */
  stop: () => void;
}

/**
 * Create and initialize a complete data stream service
 *
 * @example
 * ```typescript
 * const service = await createDataStream({
 *   s3Config: {
 *     bucket: 'my-trading-data',
 *     prefix: 'trades/',
 *     region: 'us-east-1',
 *   },
 * });
 *
 * // Query data
 * const entries = service.consumer.getByTimeRange(
 *   Date.now() - 3600000, // 1 hour ago
 *   Date.now()
 * );
 *
 * // Subscribe to real-time updates
 * service.store.subscribe((entry) => {
 *   console.log('New entry:', entry);
 * });
 *
 * // Stop the service when done
 * service.stop();
 * ```
 */
export async function createDataStream(options: DataStreamOptions): Promise<DataStreamService> {
  const { s3Config, loadInitialData = true, startWatching = true } = options;

  // Create the store
  const store = new TimeSeriesStore();

  // Create the ingester
  const ingester = new S3Ingester(store, s3Config);

  // Create the consumer
  const consumer = new DataConsumer(store);

  // Load initial data if requested
  if (loadInitialData) {
    const result = await ingester.loadInitialData();
    console.log(`Initial load complete: ${result.entriesLoaded} entries from ${result.filesProcessed} files`);
    if (result.errors.length > 0) {
      console.warn(`Errors during initial load:`, result.errors);
    }
  }

  // Start watching for new files if requested
  if (startWatching) {
    await ingester.startWatching();
  }

  return {
    store,
    ingester,
    consumer,
    stop: () => {
      ingester.stopWatching();
    },
  };
}

/**
 * Create a standalone TimeSeriesStore without S3 integration
 * Useful for testing or when data is loaded from other sources
 *
 * @example
 * ```typescript
 * const store = createStore();
 * const consumer = new DataConsumer(store);
 *
 * // Manually insert data
 * store.insert({
 *   timestamp: Date.now(),
 *   price: 100.50,
 *   size: 10,
 *   side: 'buy',
 *   source: 'manual',
 * });
 *
 * // Query data
 * const entries = consumer.getByTimeRange(start, end);
 * ```
 */
export function createStore(): TimeSeriesStore {
  return new TimeSeriesStore();
}