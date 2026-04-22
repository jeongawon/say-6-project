import { BrowserRouter, Routes, Route } from "react-router-dom";

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50">
        <header className="bg-blue-700 text-white px-6 py-4">
          <h1 className="text-xl font-bold">
            Emergency Multimodal Orchestrator
          </h1>
        </header>

        <main className="p-6">
          <Routes>
            <Route path="/" element={<Home />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

function Home() {
  return (
    <div className="max-w-2xl mx-auto text-center mt-20">
      <h2 className="text-2xl font-semibold mb-4">Dashboard</h2>
      <p className="text-gray-600">프론트엔드 스켈레톤 준비 완료</p>
    </div>
  );
}

export default App;
