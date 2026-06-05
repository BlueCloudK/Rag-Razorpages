using System.Collections.Generic;
using System.Threading.Tasks;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public interface IOrganizationService
    {
        Task<OrganizationDto?> GetCurrentOrganizationAsync();
        Task<int?> GetCurrentOrganizationIdAsync();
        Task<bool> CanManageCurrentOrganizationAsync();
        Task<OrganizationDashboardDto> GetDashboardAsync();
        Task<List<OrganizationMemberDto>> GetMembersAsync();
    }
}
