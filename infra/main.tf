#Data and locals
data "aws_availability_zones" "this" {
  state = "available"
}

locals {
  name = var.project
  tags = merge(
    var.tags,
    {
      Name = var.project
    }
  )

  #2 AZ
  az_a = data.aws_availability_zones.this.names[0]
  az_b = data.aws_availability_zones.this.names[1]

  #VPC CIDR
  vpc_cidr = var.vpc_cidr

  # /24 blocks per layer (public/app/data), in 2 AZs
  public_a_cidr = "10.0.1.0/24"
  public_b_cidr = "10.0.11.0/24"
  private_app_a_cidr = "10.0.2.0/24"
  private_app_b_cidr = "10.0.12.0/24"
  private_data_a_cidr = "10.0.3.0/24"
  private_data_b_cidr = "10.0.13.0/24"
}

# VPC and networking
resource "aws_vpc" "main" {
  cidr_block = local.vpc_cidr
  enable_dns_support = true
  enable_dns_hostnames = true

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-vpc"
    }
  )
}

#public IGW
resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-igw"
    }
  )
}

# public subnets for ALB and NAT
resource "aws_subnet" "public_a" {
  vpc_id = aws_vpc.main.id
  cidr_block = local.public_a_cidr
  availability_zone = local.az_a
  map_public_ip_on_launch = true

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-public-a"
      Tier = "public"
      "kubernetes.io/role/elb" = "1"
    }
  )
}

resource "aws_subnet" "public_b" {
  vpc_id = aws_vpc.main.id
  cidr_block = local.public_b_cidr
  availability_zone = local.az_b
  map_public_ip_on_launch = true

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-public-b"
      Tier = "public"
      "kubernetes.io/role/elb" = "1"
    }
  )
}

# Private app subnets (EKS nodes)
resource "aws_subnet" "private_app_a" {
  vpc_id = aws_vpc.main.id
  cidr_block = local.private_app_a_cidr
  availability_zone = local.az_a

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-app-a"
      Tier = "app"
      "kubernetes.io/role/internal-elb" = "1"
    }
  )
}

resource "aws_subnet" "private_app_b" {
  vpc_id = aws_vpc.main.id
  cidr_block = local.private_app_b_cidr
  availability_zone = local.az_b

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-app-b"
      Tier = "app"
      "kubernetes.io/role/internal-elb" = "1"
    }
  )
}

#private data subnets (RDS and data layer)
resource "aws_subnet" "private_data_a" {
  vpc_id = aws_vpc.main.id
  cidr_block = local.private_data_a_cidr
  availability_zone = local.az_a

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-data-a"
      Tier = "data"
    }
  )
}

resource "aws_subnet" "private_data_b" {
  vpc_id = aws_vpc.main.id
  cidr_block = local.private_data_b_cidr
  availability_zone = local.az_b

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-data-b"
      Tier = "data"
    }
  )
}

#public route table (to internet via IGW)
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-rt-public"
    }
  )
}

resource "aws_route" "public_to_internet" {
  route_table_id = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id = aws_internet_gateway.igw.id
}

resource "aws_route_table_association" "public_a" {
  route_table_id = aws_route_table.public.id
  subnet_id = aws_subnet.public_a.id
}

resource "aws_route_table_association" "public_b" {
  route_table_id = aws_route_table.public.id
  subnet_id = aws_subnet.public_b.id
}

#NAT Gateway (single AZ, in public subnet A)
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-eip-nat"
    }
  )
}

resource "aws_nat_gateway" "nat" {
  allocation_id = aws_eip.nat.id
  subnet_id = aws_subnet.public_a.id

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-nat"
    }
  )

  depends_on = [aws_internet_gateway.igw]
}

#Private route table (to internet via NAT)
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-rt-private"
    }
  )
}

resource "aws_route" "private_to_nat" {
  route_table_id = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id = aws_nat_gateway.nat.id
}

# private subnets to private route table
resource "aws_route_table_association" "app_a" {
  route_table_id = aws_route_table.private.id
  subnet_id = aws_subnet.private_app_a.id
}

resource "aws_route_table_association" "app_b" {
  route_table_id = aws_route_table.private.id
  subnet_id = aws_subnet.private_app_b.id
}

resource "aws_route_table_association" "data_a" {
  route_table_id = aws_route_table.private.id
  subnet_id = aws_subnet.private_data_a.id
}

resource "aws_route_table_association" "data_b" {
  route_table_id = aws_route_table.private.id
  subnet_id = aws_subnet.private_data_b.id
}

#EKS cluster for HR portal and Keycloak
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name = local.name
  kubernetes_version = "1.31"

  endpoint_public_access = true

  enable_cluster_creator_admin_permissions = true

  addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
      before_compute = true
    }
  }

  # Managed Node Group for application workloads
  eks_managed_node_groups = {
    general = {
      min_size = 1
      max_size = 3
      desired_size = 2

      instance_types = ["t3.medium"]
      capacity_type  = "ON_DEMAND"

      subnet_ids = [
        aws_subnet.private_app_a.id,
        aws_subnet.private_app_b.id,
      ]
    }
  }

  #VPC and subnets for the cluster
  vpc_id = aws_vpc.main.id

  subnet_ids = [
    aws_subnet.private_app_a.id,
    aws_subnet.private_app_b.id,
  ]

  tags = local.tags
}

#HR RDS networking + instance

#subnet group for RDS which uses the private data subnets
resource "aws_db_subnet_group" "data" {
  name = "${var.project}-db-subnets"
  subnet_ids = [
    aws_subnet.private_data_a.id,
    aws_subnet.private_data_b.id,
  ]

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-db-subnets"
    }
  )
}

# Security group for RDS: only allow from the VPC
resource "aws_security_group" "rds" {
  name = "${var.project}-rds-sg"
  description = "Security group for HR RDS"
  vpc_id = aws_vpc.main.id

  #allow Postgres from within the VPC CIDR, further implementation will be to restrict to Node access
  ingress {
    from_port = 5432
    to_port = 5432
    protocol = "tcp"
    cidr_blocks = [local.vpc_cidr]
  }

  egress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-rds-sg"
    }
  )
}

#HR RDS
resource "aws_db_instance" "hr" {
  identifier = "${var.project}-hr-db"
  engine = "postgres"
  instance_class = "db.t3.micro"

  allocated_storage = 20

  db_name = "hr_portal"
  username = var.hr_db_user
  password = var.hr_db_password

  db_subnet_group_name = aws_db_subnet_group.data.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  publicly_accessible  = false
  skip_final_snapshot  = true
  deletion_protection  = false

  tags = merge(
    local.tags,
    {
      Name = "${var.project}-hr-db"
    }
  )
}
