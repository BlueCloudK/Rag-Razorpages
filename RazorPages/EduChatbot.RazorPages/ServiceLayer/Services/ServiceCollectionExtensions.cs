using DataAccessLayer.Data;
using DataAccessLayer.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace ServiceLayer.Services
{
    public static class ServiceCollectionExtensions
    {
        public static IServiceCollection AddEduChatbotServices(this IServiceCollection services, IConfiguration configuration)
        {
            services.AddDbContext<ApplicationDbContext>(options =>
                options.UseSqlServer(configuration.GetConnectionString("DefaultConnection")));

            services.AddIdentity<ApplicationUser, IdentityRole>(options =>
                {
                    options.Password.RequireDigit = true;
                    options.Password.RequireLowercase = true;
                    options.Password.RequireUppercase = true;
                    options.Password.RequireNonAlphanumeric = false;
                    options.Password.RequiredLength = 8;
                    options.User.RequireUniqueEmail = true;
                })
                .AddEntityFrameworkStores<ApplicationDbContext>()
                .AddDefaultTokenProviders();

            services.ConfigureApplicationCookie(options =>
            {
                options.LoginPath = "/Account/Login";
                options.AccessDeniedPath = "/Account/AccessDenied";
            });

            services.AddAuthorization(options =>
            {
                options.FallbackPolicy = new AuthorizationPolicyBuilder()
                    .RequireAuthenticatedUser()
                    .Build();
            });

            services.AddHttpContextAccessor();
            services.AddScoped<IAuthService, AuthService>();
            services.AddScoped<ICurrentUserService, CurrentUserService>();
            services.AddScoped<IAccessControlService, AccessControlService>();
            services.AddScoped<ISubscriptionService, SubscriptionService>();
            services.AddScoped<IUsageService, UsageService>();
            services.AddScoped<IAuditLogService, AuditLogService>();
            services.AddScoped<IOrganizationService, OrganizationService>();
            services.AddScoped<IBillingService, BillingService>();
            services.AddScoped<IAdminService, AdminService>();
            services.AddScoped<ISubjectService, SubjectService>();
            services.AddScoped<IDocumentService, DocumentService>();
            services.AddScoped<IChatService, ChatService>();
            services.AddHostedService<PythonAIServiceRunner>();

            return services;
        }
    }
}
