using System.Threading.Tasks;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public interface IRagLabService
    {
        Task<RagLabDashboardDto> GetDashboardAsync();
    }
}
