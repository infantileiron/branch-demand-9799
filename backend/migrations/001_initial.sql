--
-- PostgreSQL database dump
--

\restrict lXFB6fNpI4rXcksEIua5wCwsTi9dYlOU8AAtbpjjkZcdJKYCuoHM9Ug1Wwit1mc

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audits (
    id integer NOT NULL,
    actor character varying(100),
    action character varying(200),
    created character varying(40)
);


--
-- Name: audits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audits_id_seq OWNED BY public.audits.id;


--
-- Name: daily_volumes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_volumes (
    id integer NOT NULL,
    branch character varying(30) NOT NULL,
    day character varying(10) NOT NULL,
    volume integer NOT NULL,
    note text
);


--
-- Name: daily_volumes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.daily_volumes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: daily_volumes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.daily_volumes_id_seq OWNED BY public.daily_volumes.id;


--
-- Name: forecast_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forecast_runs (
    id integer NOT NULL,
    name character varying(100),
    branch character varying(30),
    backtest_days integer,
    alpha double precision,
    beta double precision,
    state character varying(20),
    result json,
    error text
);


--
-- Name: forecast_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.forecast_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: forecast_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.forecast_runs_id_seq OWNED BY public.forecast_runs.id;


--
-- Name: staffings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staffings (
    id integer NOT NULL,
    run_id integer,
    capacity integer,
    model character varying(30),
    schedule json,
    note text,
    status character varying(20)
);


--
-- Name: staffings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.staffings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: staffings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.staffings_id_seq OWNED BY public.staffings.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying(100),
    password character varying(200),
    role character varying(20)
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: audits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audits ALTER COLUMN id SET DEFAULT nextval('public.audits_id_seq'::regclass);


--
-- Name: daily_volumes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_volumes ALTER COLUMN id SET DEFAULT nextval('public.daily_volumes_id_seq'::regclass);


--
-- Name: forecast_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecast_runs ALTER COLUMN id SET DEFAULT nextval('public.forecast_runs_id_seq'::regclass);


--
-- Name: staffings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staffings ALTER COLUMN id SET DEFAULT nextval('public.staffings_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: audits audits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audits
    ADD CONSTRAINT audits_pkey PRIMARY KEY (id);


--
-- Name: daily_volumes daily_volumes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_volumes
    ADD CONSTRAINT daily_volumes_pkey PRIMARY KEY (id);


--
-- Name: forecast_runs forecast_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecast_runs
    ADD CONSTRAINT forecast_runs_pkey PRIMARY KEY (id);


--
-- Name: staffings staffings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staffings
    ADD CONSTRAINT staffings_pkey PRIMARY KEY (id);


--
-- Name: daily_volumes uq_branch_day; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_volumes
    ADD CONSTRAINT uq_branch_day UNIQUE (branch, day);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: staffings staffings_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staffings
    ADD CONSTRAINT staffings_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.forecast_runs(id);


--
-- PostgreSQL database dump complete
--

\unrestrict lXFB6fNpI4rXcksEIua5wCwsTi9dYlOU8AAtbpjjkZcdJKYCuoHM9Ug1Wwit1mc

