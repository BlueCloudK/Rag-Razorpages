using System.Collections.Generic;
using System.Threading.Tasks;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public interface ISubjectService
    {
        Task<List<SubjectDto>> GetAllAsync(bool includeDocuments = false);
        Task<SubjectDto?> GetByIdAsync(int id);
        Task CreateAsync(SubjectInput input);
        Task<bool> UpdateAsync(SubjectInput input);
        Task<bool> DeleteAsync(int id);
        Task<bool> ExistsAsync(int id);
    }
}
