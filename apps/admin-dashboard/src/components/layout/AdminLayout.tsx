import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

export const AdminLayout: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col antialiased" dir="rtl">
      <Sidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen((prev) => !prev)}
      />
      <Topbar sidebarOpen={sidebarOpen} />

      <main
        className={`flex-1 transition-all duration-300 pt-20 px-8 pb-12 ${
          sidebarOpen ? 'mr-64' : 'mr-20'
        }`}
      >
        <div className="max-w-7xl mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
};
