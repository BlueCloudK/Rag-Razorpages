using System.Threading;
using System.Threading.Tasks;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public interface IChatService
    {
        Task<ChatPageDto?> GetChatPageAsync(int subjectId, int? sessionId = null);
        Task<ChatSendResult> SendMessageAsync(int subjectId, string content, int? sessionId = null, CancellationToken cancellationToken = default);
        Task<int?> CreateSessionAsync(int subjectId);
        Task<bool> DeleteSessionAsync(int subjectId, int sessionId);
        Task<bool> AddSubjectMemberAsync(int subjectId, string userId, string roleInSubject);
        Task<bool> UpdateSubjectMemberRoleAsync(int subjectId, int membershipId, string roleInSubject);
        Task<bool> RemoveSubjectMemberAsync(int subjectId, int membershipId);
    }
}
