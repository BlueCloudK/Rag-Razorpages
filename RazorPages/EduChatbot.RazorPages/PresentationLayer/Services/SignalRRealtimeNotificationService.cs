using Microsoft.AspNetCore.SignalR;
using PresentationLayer.Hubs;
using ServiceLayer.Services;

namespace PresentationLayer.Services
{
    public class SignalRRealtimeNotificationService : IRealtimeNotificationService
    {
        private readonly IHubContext<WorkspaceHub> _hub;

        public SignalRRealtimeNotificationService(IHubContext<WorkspaceHub> hub)
        {
            _hub = hub;
        }

        public Task SubjectChangedAsync(string action, int subjectId, string? subjectName = null)
        {
            return _hub.Clients.All.SendAsync("SubjectChanged", new
            {
                action,
                subjectId,
                subjectName
            });
        }

        public Task DocumentChangedAsync(string action, int subjectId, int? documentId = null, string? fileName = null)
        {
            return _hub.Clients.All.SendAsync("DocumentChanged", new
            {
                action,
                subjectId,
                documentId,
                fileName
            });
        }

        public Task MembershipChangedAsync(string action, int subjectId, string? userId = null)
        {
            return _hub.Clients.All.SendAsync("MembershipChanged", new
            {
                action,
                subjectId,
                userId
            });
        }

        public Task AdminChangedAsync(string action)
        {
            return _hub.Clients.All.SendAsync("AdminChanged", new { action });
        }
    }
}
