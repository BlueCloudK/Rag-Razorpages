using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.SignalR;

namespace PresentationLayer.Hubs
{
    [Authorize]
    public class WorkspaceHub : Hub
    {
    }
}
