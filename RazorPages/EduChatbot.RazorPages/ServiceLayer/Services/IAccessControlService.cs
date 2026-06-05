using System.Threading.Tasks;

namespace ServiceLayer.Services
{
    public interface IAccessControlService
    {
        Task<bool> IsAdminAsync();
        Task<bool> CanViewSubjectAsync(int subjectId);
        Task<bool> CanManageSubjectAsync(int subjectId);
        Task<bool> CanUploadDocumentAsync(int subjectId);
        Task<bool> CanDeleteDocumentAsync(int subjectId);
    }
}
