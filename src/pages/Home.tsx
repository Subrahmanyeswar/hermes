// Import React and required hooks
import React, { useState } from 'react';

// Import Tailwind CSS utility classes

const Home = () => {
  // State to store user responses
  const [responses, setResponses] = useState({
    experience: '',
    interests: []
  });

  // Function to handle form submission
  const handleSubmit = (e) => {
    e.preventDefault();
    // Process responses and suggest a career path
    // For simplicity, let's assume a hardcoded response
    alert('Career suggestion based on your responses');
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
      <h1 className="text-3xl font-bold text-blue-700 mb-8">Edupath</h1>
      <form onSubmit={handleSubmit} className="max-w-md mx-auto bg-white p-6 rounded-lg shadow-lg">
        <div className="mb-4">
          <label htmlFor="experience" className="block text-sm font-medium text-gray-700">Experience Level:</label>
          <input
            type="text"
            id="experience"
            name="experience"
            value={responses.experience}
            onChange={(e) => setResponses({ ...responses, experience: e.target.value })}
            className="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
          />
        </div>
        <div className="mb-4">
          <label htmlFor="interests" className="block text-sm font-medium text-gray-700">Interests (comma-separated):</label>
          <input
            type="text"
            id="interests"
            name="interests"
            value={responses.interests}
            onChange={(e) => setResponses({ ...responses, interests: e.target.value.split(',') })}
            className="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
          />
        </div>
        <button type="submit" className="w-full bg-blue-600 text-white py-2 px-4 border border-transparent rounded-md shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">Submit</button>
      </form>
    </div>
  );
};

export default Home;