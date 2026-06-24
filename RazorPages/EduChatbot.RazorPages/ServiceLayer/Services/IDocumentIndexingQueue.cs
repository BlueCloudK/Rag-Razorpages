using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;

namespace ServiceLayer.Services
{
    public record DocumentIndexingJob(int DocumentId);

    public interface IDocumentIndexingQueue
    {
        ValueTask QueueAsync(DocumentIndexingJob job, CancellationToken cancellationToken = default);
        ValueTask<DocumentIndexingJob> DequeueAsync(CancellationToken cancellationToken);
    }

    public class DocumentIndexingQueue : IDocumentIndexingQueue
    {
        private readonly Channel<DocumentIndexingJob> _queue = Channel.CreateUnbounded<DocumentIndexingJob>(
            new UnboundedChannelOptions
            {
                SingleReader = true,
                SingleWriter = false
            });

        public ValueTask QueueAsync(DocumentIndexingJob job, CancellationToken cancellationToken = default)
            => _queue.Writer.WriteAsync(job, cancellationToken);

        public ValueTask<DocumentIndexingJob> DequeueAsync(CancellationToken cancellationToken)
            => _queue.Reader.ReadAsync(cancellationToken);
    }
}
