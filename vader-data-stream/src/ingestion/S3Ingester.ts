import {
  S3Client,
  ListObjectsV2Command,
  GetObjectCommand,
  ListObjectsV2CommandOutput,
} from '@aws-sdk/client-s3';
import {
  SQSClient,
  ReceiveMessageCommand,
  DeleteMessageCommand,
  Message,
} from '@aws-sdk/client-sqs';
import { TradeEntry, S3IngestConfig, LoadResult } from '../types.js';
import { TimeSeriesStore } from '../store/TimeSeriesStore.js';

/**
 * Handles loading and watching S3 for JSON trade data files
 */
export class S3Ingester {
  private s3Client: S3Client;
  private sqsClient: SQSClient | null = null;
  private store: TimeSeriesStore;
  private config: S3IngestConfig;
  private processedKeys: Set<string> = new Set();
  private pollingTimer: NodeJS.Timeout | null = null;
  private isPolling: boolean = false;

  constructor(store: TimeSeriesStore, config: S3IngestConfig) {
    this.store = store;
    this.config = config;

    this.s3Client = new S3Client({
      region: config.region || process.env.AWS_REGION || 'us-east-1',
    });

    if (config.sqsQueueUrl) {
      this.sqsClient = new SQSClient({
        region: config.region || process.env.AWS_REGION || 'us-east-1',
      });
    }
  }

  /**
   * Load all existing data from S3 bucket
   */
  async loadInitialData(): Promise<LoadResult> {
    const result: LoadResult = {
      filesProcessed: 0,
      entriesLoaded: 0,
      errors: [],
    };

    let continuationToken: string | undefined;

    do {
      const response: ListObjectsV2CommandOutput = await this.s3Client.send(
        new ListObjectsV2Command({
          Bucket: this.config.bucket,
          Prefix: this.config.prefix || '',
          ContinuationToken: continuationToken,
        })
      );

      if (!response.Contents || response.Contents.length === 0) {
        break;
      }

      for (const object of response.Contents) {
        if (!object.Key) continue;

        // Skip non-JSON files
        if (!object.Key.endsWith('.json')) continue;

        try {
          const entries = await this.loadFile(object.Key);
          this.store.insertBatch(entries);
          this.processedKeys.add(object.Key);
          result.filesProcessed++;
          result.entriesLoaded += entries.length;
        } catch (error) {
          result.errors.push({
            key: object.Key,
            error: error instanceof Error ? error.message : String(error),
          });
        }
      }

      continuationToken = response.NextContinuationToken;
    } while (continuationToken);

    return result;
  }

  /**
   * Load a single JSON file from S3
   */
  private async loadFile(key: string): Promise<TradeEntry[]> {
    const response = await this.s3Client.send(
      new GetObjectCommand({
        Bucket: this.config.bucket,
        Key: key,
      })
    );

    if (!response.Body) {
      throw new Error(`No body in response for ${key}`);
    }

    const body = await response.Body.transformToString('utf-8');
    const data = JSON.parse(body);

    // Handle both single entry and array of entries
    const entries: TradeEntry[] = Array.isArray(data) ? data : [data];

    // Validate entries have required fields
    return entries.filter((entry) => {
      return (
        typeof entry.timestamp === 'number' &&
        typeof entry.price === 'number' &&
        typeof entry.size === 'number' &&
        (entry.side === 'buy' || entry.side === 'sell') &&
        typeof entry.source === 'string'
      );
    });
  }

  /**
   * Start watching for new files via SQS or polling
   */
  async startWatching(): Promise<void> {
    if (this.config.sqsQueueUrl && this.sqsClient) {
      await this.startSqsListener();
    } else {
      this.startPolling();
    }
  }

  /**
   * Start listening to SQS for S3 event notifications
   */
  private async startSqsListener(): Promise<void> {
    if (!this.sqsClient || !this.config.sqsQueueUrl) return;

    const pollSqs = async () => {
      while (this.isPolling) {
        try {
          const response = await this.sqsClient!.send(
            new ReceiveMessageCommand({
              QueueUrl: this.config.sqsQueueUrl!,
              MaxNumberOfMessages: 10,
              WaitTimeSeconds: 20, // Long polling
            })
          );

          if (!response.Messages) continue;

          await this.processSqsMessages(response.Messages);
        } catch (error) {
          console.error('Error polling SQS:', error);
          // Wait before retrying
          await new Promise((resolve) => setTimeout(resolve, 5000));
        }
      }
    };

    this.isPolling = true;
    pollSqs();
  }

  /**
   * Process SQS messages containing S3 event notifications
   */
  private async processSqsMessages(messages: Message[]): Promise<void> {
    for (const message of messages) {
      if (!message.Body || !message.ReceiptHandle) continue;

      try {
        const s3Event = JSON.parse(message.Body);

        // S3 event structure: { Records: [{ s3: { object: { key: string } } }] }
        if (s3Event.Records && Array.isArray(s3Event.Records)) {
          for (const record of s3Event.Records) {
            const key = record.s3?.object?.key;
            if (!key || !key.endsWith('.json')) continue;
            if (this.processedKeys.has(key)) continue;

            try {
              const entries = await this.loadFile(key);
              this.store.insertBatch(entries);
              this.processedKeys.add(key);
            } catch (error) {
              console.error(`Error loading file ${key}:`, error);
            }
          }
        }

        // Delete the message after processing
        await this.sqsClient!.send(
          new DeleteMessageCommand({
            QueueUrl: this.config.sqsQueueUrl!,
            ReceiptHandle: message.ReceiptHandle,
          })
        );
      } catch (error) {
        console.error('Error processing SQS message:', error);
      }
    }
  }

  /**
   * Start polling S3 for new files (fallback when SQS is not configured)
   */
  private startPolling(): void {
    const interval = this.config.pollingInterval || 30000; // Default: 30 seconds

    this.isPolling = true;

    const poll = async () => {
      if (!this.isPolling) return;

      try {
        let continuationToken: string | undefined;

        do {
          const response = await this.s3Client.send(
            new ListObjectsV2Command({
              Bucket: this.config.bucket,
              Prefix: this.config.prefix || '',
              ContinuationToken: continuationToken,
            })
          );

          if (response.Contents) {
            for (const object of response.Contents) {
              if (!object.Key || !object.Key.endsWith('.json')) continue;
              if (this.processedKeys.has(object.Key)) continue;

              try {
                const entries = await this.loadFile(object.Key);
                this.store.insertBatch(entries);
                this.processedKeys.add(object.Key);
              } catch (error) {
                console.error(`Error loading file ${object.Key}:`, error);
              }
            }
          }

          continuationToken = response.NextContinuationToken;
        } while (continuationToken);
      } catch (error) {
        console.error('Error polling S3:', error);
      }

      // Schedule next poll
      this.pollingTimer = setTimeout(poll, interval);
    };

    poll();
  }

  /**
   * Stop watching for new files
   */
  stopWatching(): void {
    this.isPolling = false;
    if (this.pollingTimer) {
      clearTimeout(this.pollingTimer);
      this.pollingTimer = null;
    }
  }

  /**
   * Get the count of processed files
   */
  get processedCount(): number {
    return this.processedKeys.size;
  }
}