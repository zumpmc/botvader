import { TimeSeriesStore } from '../src/store/TimeSeriesStore';
import { TradeEntry } from '../src/types';

describe('TimeSeriesStore', () => {
  let store: TimeSeriesStore;

  beforeEach(() => {
    store = new TimeSeriesStore();
  });

  afterEach(() => {
    store.clear();
  });

  describe('insert', () => {
    it('should insert a single entry', () => {
      const entry: TradeEntry = {
        timestamp: 1700000000000,
        price: 100.50,
        size: 10,
        side: 'buy',
        source: 'test',
      };

      store.insert(entry);

      expect(store.size).toBe(1);
      const stats = store.getStats();
      expect(stats.totalEntries).toBe(1);
      expect(stats.earliestTimestamp).toBe(1700000000000);
      expect(stats.latestTimestamp).toBe(1700000000000);
    });

    it('should maintain sorted order within buckets', () => {
      const entries: TradeEntry[] = [
        { timestamp: 1700000003000, price: 100, size: 1, side: 'buy', source: 'test' },
        { timestamp: 1700000001000, price: 101, size: 2, side: 'sell', source: 'test' },
        { timestamp: 1700000002000, price: 102, size: 3, side: 'buy', source: 'test' },
      ];

      entries.forEach((e) => store.insert(e));

      const results = store.getByTimeRange({
        start: 1700000000000,
        end: 1700000004000,
      });

      expect(results).toHaveLength(3);
      expect(results[0].timestamp).toBe(1700000001000);
      expect(results[1].timestamp).toBe(1700000002000);
      expect(results[2].timestamp).toBe(1700000003000);
    });
  });

  describe('insertBatch', () => {
    it('should insert multiple entries', () => {
      const entries: TradeEntry[] = [
        { timestamp: 1700000001000, price: 100, size: 1, side: 'buy', source: 'test' },
        { timestamp: 1700000002000, price: 101, size: 2, side: 'sell', source: 'test' },
        { timestamp: 1700000003000, price: 102, size: 3, side: 'buy', source: 'test' },
      ];

      store.insertBatch(entries);

      expect(store.size).toBe(3);
    });

    it('should handle unsorted input', () => {
      const entries: TradeEntry[] = [
        { timestamp: 1700000003000, price: 100, size: 1, side: 'buy', source: 'test' },
        { timestamp: 1700000001000, price: 101, size: 2, side: 'sell', source: 'test' },
        { timestamp: 1700000002000, price: 102, size: 3, side: 'buy', source: 'test' },
      ];

      store.insertBatch(entries);

      const results = store.getByTimeRange({
        start: 1700000000000,
        end: 1700000004000,
      });

      expect(results[0].timestamp).toBe(1700000001000);
      expect(results[1].timestamp).toBe(1700000002000);
      expect(results[2].timestamp).toBe(1700000003000);
    });
  });

  describe('getByTimeRange', () => {
    beforeEach(() => {
      // Insert test data across multiple buckets
      const baseTime = 1700000000000;
      for (let i = 0; i < 100; i++) {
        store.insert({
          timestamp: baseTime + i * 1000, // 1 second apart
          price: 100 + i,
          size: i + 1,
          side: i % 2 === 0 ? 'buy' : 'sell',
          source: i < 50 ? 'source1' : 'source2',
        });
      }
    });

    it('should return entries within the time range', () => {
      const results = store.getByTimeRange({
        start: 1700000000000,
        end: 1700000005000,
      });

      expect(results).toHaveLength(5);
    });

    it('should filter by source', () => {
      const results = store.getByTimeRange({
        start: 1700000000000,
        end: 1700000100000,
        source: 'source1',
      });

      expect(results).toHaveLength(50);
      results.forEach((r) => expect(r.source).toBe('source1'));
    });

    it('should filter by side', () => {
      const results = store.getByTimeRange({
        start: 1700000000000,
        end: 1700000100000,
        side: 'buy',
      });

      expect(results).toHaveLength(50);
      results.forEach((r) => expect(r.side).toBe('buy'));
    });

    it('should respect limit', () => {
      const results = store.getByTimeRange({
        start: 1700000000000,
        end: 1700000100000,
        limit: 10,
      });

      expect(results).toHaveLength(10);
    });

    it('should return empty array for empty range', () => {
      const results = store.getByTimeRange({
        start: 1800000000000,
        end: 1800000100000,
      });

      expect(results).toHaveLength(0);
    });
  });

  describe('getAtTime', () => {
    it('should return entries at exact timestamp', () => {
      const timestamp = 1700000000000;
      store.insert({
        timestamp,
        price: 100,
        size: 1,
        side: 'buy',
        source: 'test',
      });

      const results = store.getAtTime(timestamp);
      expect(results).toHaveLength(1);
    });

    it('should return multiple entries at same timestamp', () => {
      const timestamp = 1700000000000;
      store.insert({
        timestamp,
        price: 100,
        size: 1,
        side: 'buy',
        source: 'test1',
      });
      store.insert({
        timestamp,
        price: 101,
        size: 2,
        side: 'sell',
        source: 'test2',
      });

      const results = store.getAtTime(timestamp);
      expect(results).toHaveLength(2);
    });

    it('should return empty array when no entries at timestamp', () => {
      const results = store.getAtTime(1700000000000);
      expect(results).toHaveLength(0);
    });
  });

  describe('getNearest', () => {
    beforeEach(() => {
      store.insert({
        timestamp: 1700000000000,
        price: 100,
        size: 1,
        side: 'buy',
        source: 'test',
      });
      store.insert({
        timestamp: 1700000010000, // 10 seconds later
        price: 101,
        size: 2,
        side: 'sell',
        source: 'test',
      });
    });

    it('should return exact match when exists', () => {
      const result = store.getNearest(1700000000000);
      expect(result).not.toBeNull();
      expect(result?.timestamp).toBe(1700000000000);
    });

    it('should return nearest entry within tolerance', () => {
      const result = store.getNearest(1700000005000); // 5 seconds after first
      expect(result).not.toBeNull();
      expect(result?.timestamp).toBe(1700000010000); // Closer to second entry
    });

    it('should return null when no entry within tolerance', () => {
      // Query at 500ms between entries (5000ms away from each), with 100ms tolerance
      const result = store.getNearest(1700000005000, 100);
      expect(result).toBeNull();
    });

    it('should find entries in adjacent buckets', () => {
      // Insert entry in minute bucket 1
      store.insert({
        timestamp: 1700000060000, // 1 minute later
        price: 102,
        size: 3,
        side: 'buy',
        source: 'test',
      });

      // Query near bucket boundary
      const result = store.getNearest(1700000059000, 5000);
      expect(result).not.toBeNull();
    });
  });

  describe('subscribe', () => {
    it('should emit entry event on insert', (done) => {
      const entry: TradeEntry = {
        timestamp: 1700000000000,
        price: 100,
        size: 1,
        side: 'buy',
        source: 'test',
      };

      store.subscribe((received) => {
        expect(received).toEqual(entry);
        done();
      });

      store.insert(entry);
    });

    it('should return unsubscribe function', () => {
      const unsubscribe = store.subscribe(() => {
        fail('Should not be called');
      });

      unsubscribe();

      store.insert({
        timestamp: 1700000000000,
        price: 100,
        size: 1,
        side: 'buy',
        source: 'test',
      });
    });
  });

  describe('clear', () => {
    it('should remove all entries', () => {
      store.insert({
        timestamp: 1700000000000,
        price: 100,
        size: 1,
        side: 'buy',
        source: 'test',
      });

      expect(store.size).toBe(1);

      store.clear();

      expect(store.size).toBe(0);
      expect(store.isEmpty).toBe(true);
    });
  });

  describe('getStats', () => {
    it('should return correct statistics', () => {
      store.insertBatch([
        { timestamp: 1700000000000, price: 100, size: 1, side: 'buy', source: 'test' },
        { timestamp: 1700000001000, price: 101, size: 2, side: 'sell', source: 'test' },
        { timestamp: 1700000060000, price: 102, size: 3, side: 'buy', source: 'test' }, // Different minute
      ]);

      const stats = store.getStats();

      expect(stats.totalEntries).toBe(3);
      expect(stats.bucketCount).toBe(2); // Two different minutes
      expect(stats.earliestTimestamp).toBe(1700000000000);
      expect(stats.latestTimestamp).toBe(1700000060000);
    });
  });
});

describe('DataConsumer', () => {
  // Import DataConsumer for testing
  // Tests would be similar but focus on the API layer
});