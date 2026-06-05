using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public interface IDocumentService
    {
        Task<List<DocumentDto>> GetAllAsync();
        Task<DocumentDto?> GetByIdAsync(int id);
        Task<DocumentChunkInspectorDto?> GetChunkInspectorAsync(int id, int offset = 0, int limit = 8);
        Task<DocumentUploadResult> UploadAndIndexAsync(int subjectId, IFormFile file, string? returnUrl);
        Task<bool> DeleteAsync(int id);
    }
}
