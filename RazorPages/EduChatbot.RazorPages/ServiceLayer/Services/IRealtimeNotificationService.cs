using System.Threading.Tasks;

namespace ServiceLayer.Services
{
    public interface IRealtimeNotificationService
    {
        Task SubjectChangedAsync(string action, int subjectId, string? subjectName = null);
        Task DocumentChangedAsync(string action, int subjectId, int? documentId = null, string? fileName = null);
        Task MembershipChangedAsync(string action, int subjectId, string? userId = null);
        Task AdminChangedAsync(string action);
    }

    public class NoopRealtimeNotificationService : IRealtimeNotificationService
    {
        public Task SubjectChangedAsync(string action, int subjectId, string? subjectName = null) => Task.CompletedTask;

        public Task DocumentChangedAsync(string action, int subjectId, int? documentId = null, string? fileName = null) => Task.CompletedTask;

        public Task MembershipChangedAsync(string action, int subjectId, string? userId = null) => Task.CompletedTask;

        public Task AdminChangedAsync(string action) => Task.CompletedTask;
    }
}
